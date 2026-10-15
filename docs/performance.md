# 当前提交：仅修改kernel.asc

提交工程以用户最初上传的ZIP为基准，只允许kernel.asc内容不同。CMakeLists.txt、main.asc、run.sh、data_utils.h和三个Python脚本均逐字节保持原样；包内无manifest、测试工具或其他新增文件。

本次将内核自写的if constexpr类型分派改为函数重载。频率计算、角度缩减、FMA、DMA与分块策略保持一致。

## 当前版本验收

- 使用原始run.sh原样编译并执行；原始校验PASS，最大绝对误差2.6226043701171875e-6。
- 原始main.asc固定选择设备0，因此本次由task-submit独占申请单卡0，任务执行后已释放。
- 29/29代表用例与1010/1010维度扫描通过；位置0逐位恒等及输出哨兵检查通过。
- 原始CMakeLists.txt保持CMAKE_CXX_STANDARD 14，不添加额外编译参数；ASC使用CANN工具链默认语言模式。

| 用例 | 当前原生event us |
|---|---:|
| deepseek_half | 30.896 |
| deepseek_float | 34.556 |
| sequence8192 | 15.390 |
| large_half | 99.122 |

典型FP16 profiling Task Duration=30.701 us。原始PMU CSV保存在benchmarks/profiles/kernel_only。

当前kernel SHA256：`a8aa639279363162549fa46c0640d5b30fb641a2942dd3f0fca9a2ead5df7781`。

打包时以固定原模板SHA256清单校验，verify_submission.py同时检查ZIP、解压目录和独立kernel；要求修改文件列表恰为["kernel.asc"]，新增和缺失文件列表为空。

---

# 以下为先前版本的历史优化记录

# 最终验收与性能报告

硬件：Ascend910_9392，48个AIV，1850 MHz；CANN 9.0.0，dav-2201。所有设备任务使用task-submit单卡短任务。

## 同卡原生性能

同一张物理卡0上，按baseline/candidate/candidate/baseline顺序交替测试。每次10轮预热、每批100次、5批计时，以两轮结果的中位数汇总。基线对应Git e35b0cc，最终kernel以SHA256标识。

| 用例 | dtype | 基线 us | 最终 us | 加速比 |
|---|---|---:|---:|---:|
| deepseek_half | float16 | 159.385 | 30.525 | 5.22× |
| deepseek_float | float32 | 135.159 | 34.220 | 3.95× |
| sequence8192 | float32 | 250.518 | 15.115 | 16.57× |
| large_half | float16 | 613.191 | 97.754 | 6.27× |

## Profiling闭环

| 阶段 | 典型FP16 Task Duration us | 平均VEC时间 us | MTE2活跃GB/s/核 | MTE3活跃GB/s/核 |
|---|---:|---:|---:|---:|
| baseline | 189.504 | 49.052 | 11.43 | 10.96 |
| v1 | 48.001 | 35.130 | 38.23 | 75.41 |
| v2 | 37.341 | 26.770 | 37.56 | 76.87 |
| final | 31.321 | 20.612 | 37.90 | 72.96 |

连续DMA和双缓冲减少搬运事务；融合sin/cos降低VEC计算；MulAddDst继续降低旋转指令数。单head的profile从v1的186.304 us降至合批后的14.500 us。每次采集的原始CSV、硬件信息及摘要保存在benchmarks/profiles。

## 正确性与提交范围

- 代表集：29/29通过，覆盖模板、FP16/FP32、非对齐、theta=1/1000/10000/500000、D=512/1024、最大位置131072、不同head数、长序列、三个路径的NaN/Inf、FP16输出溢出和尾块。
- 维度扫描：1010/1010通过，即D=16..1024全部505个偶数维度×两种dtype；包含极限位置与position=0。
- 每个代表用例均检查输出边界哨兵和position=0逐位恒等；所有用例逐元素匹配率均为100%。
- 使用附件NumPy FP32 golden及题目atol/rtol、99%通过率、最大绝对误差双重条件。平台15个隐藏点未公开，尚未在比赛平台运行；这里的加速比针对自建基线。
- 代表集设备任务内完整流程约3.78秒；1010项扫描约3.67秒。单卡交替对比约40.14秒，单个任务均有限时。

## 文件一致性

kernel SHA256：`03596725aae7802092a58a41e452b6e05b7d8f64460b1ff2678cb6f794fbcd99`。
打包脚本要求当前kernel已提交Git、完整精度集通过、结果中的源码哈希匹配当前文件；产物包含独立kernel.asc与完整模板兼容工程。
