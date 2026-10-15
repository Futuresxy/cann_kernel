# 实现与硬件映射

输入、输出和 `run_kernel` ABI 与附件一致。只接受赛题要求的连续 ND float16/float32 与 int32 positions；位置由设备读取，host 不读取或特化任何输入数据。

## 三条执行路径

- 对齐、多 head：dim 为16倍数且不大于512，整行连续 DMA。按 token/head 切块，输入输出双队列分别复用两个 UB 缓冲。向量指令 `src1RepStride=0` 广播同 token 的 cos/sin；两次 Mul 和两次 MulAddDst 完成前后半维旋转。
- 单 head：满足对齐条件、token数至少16时，最多64个 token 合批。角度按 token 生成，三角函数对整个批次连续向量化，旋转时使用不同的 repeat stride 访问 x 与紧凑 cos/sin。
- 通用：其他偶数维度用 DataCopyPad 分别装载前后两半，每行填充到16个元素的倍数。GM stride 使用字节，UB stride 使用32字节块，输出只写有效元素。dim 大于512也在一次kernel启动中处理完整前后半维，不再在host按列分区启动两次。

宽维度的512个FP32频率不能直接放入默认1536字节的kernel参数区。`WideFrequencies`保存128个FP32种子、3个FP32比例和384个int16 ULP修正值，总计1292字节。host先独立计算每个频率，再记录它与种子乘比例所得FP32值的位模式差；设备端乘法后应用整数修正，恢复对应FP32频率。修正值用于无损编码，不把频率降为FP16。全部角度、cos/sin与旋转仍在同一个kernel中完成。

## 精度路径

1. 频率在算子 host 入口以 `1.0f / pow(float(theta),float(2*i)/dim)` 计算。严格跟随附件 NumPy FP32 的除法/幂/倒数次序，避免使用 exp(log(theta)*...) 引入长位置下频率误差。
2. 频率作为算子自身的launch参数传入，不改变接口、无外部 cos/sin、无固定shape或输入输出预计算表。
3. 位置转换为FP32，FP32乘法得到与参考相同舍入的角度。
4. 使用 `2π = 6.25 + 0.033203125 - 0.000017817820413523074` 三段缩减。对于赛题位置范围和常用theta≥1，前两项乘法可以避免大角度直接相减损失。
5. 缩减后的角度除以4，在[-π/4,π/4]使用9阶sin多项式。由正平方根恢复cos，再使用两次二倍角公式恢复原角度的sin/cos。所有步骤均为FP32。
6. 旋转乘加保持FP32，FP16仅最终一次转换。FMA与分离乘加的舍入差异通过赛题误差规则验收。
7. position=0直接复制输入。通用路径补充MTE2→MTE3同步；对齐和合批路径经过VEC输出队列，保证跨流水线依赖。

`run_kernel`每条分支只调用一个kernel，宽维度分支启动后立即返回。测试runner用链接器包装实际`aclrtLaunchKernelWithHostArgs`接口，逐次检查启动数；另用非replay的msprof设备任务记录校验75次调用恰有75个AI_VECTOR_CORE任务。测试包装器不进入提交文件。

官方高阶 Sin 的输入范围和临时空间约束见[华为 Sin API](https://www.hiascend.com/document/detail/en/canncommercial/850/API/ascendcopapi/atlasascendc_api_07_0500.html)。本实现使用融合三角函数路径，并以实际设备误差与PMU指标验收。

## UB预算与分块

典型D=64、FP16、128个head的tile包含8192个元素：输入输出双缓冲65536字节，三个FP32工作区98304字节，频率/角度/sin/cos共1024字节，总计164864字节，小于192KiB。FP32将tile限制到4096个元素，对应总计115712字节。通用路径的pair容量不超过4096，最大预算约146KiB；合批路径最大预算约137KiB。

全局偏移和总任务数使用64位整数，防止B/S/H组合后溢出。每核按连续任务区间分工，保持同token的频率复用；核数取可用AIV数与任务数的较小值。

## 性能判据

保留改动需同时满足：精度通过、边界哨兵完整、原生延迟改善、profile指标支持预期。使用Task Duration评价kernel执行，使用ACL event记录原生批次平均时间，同时保留host时间；不把profiling replay过程中的event结果用于性能对比。
