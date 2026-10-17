本轮完成了“FP32队列直接计算→FP16紧凑系数→双缓冲流水”的因果比较。最终实验源码相对真实平台48.78分的817f8364基线，两个非对齐代表加速1.7253x/1.6801x，额外10点全部加速。只归档一个最终实验候选，供Mac主控审阅；没有发布production ready、改变latest或操作浏览器。

请求：`20261017T060621-unaligned-pipeline`。最终源码为 [kernel.asc](kernel.asc)，SHA256 `f32e9651514d312bdbe5bd9f238e8b29587ef0ae51555176b62b3df301ff1dc0`。它已经包含官方817f8364的宽维优化；正式operators目录仍是V9，不能把正式目录的文件误当本轮候选。完整机器记录在上级同名JSON，交接入口为 [experimental_candidate.json](experimental_candidate.json)。

这仍有已知有效输入精度限制：冻结大幅值FP16用例与父版输出逐位一致，max_abs_error仍为32>0.1。它没有被排除、重生成或标为通过。此限制继续阻止production ready；本任务明确允许归档实验版本，由主控决定是否进行用户授权的真实平台试验。服务端未新增平台提交，官方分数仍是父版48.78，不能由本地加速比推算已经达到70.01分。

先前d65529a2广播实验保持原结论：D126/FP16受益，但D254/FP32回退6.07%，未整体推广。本轮不再将紧凑广播套到FP32，也不改frequency/trig、4个分离FP32乘积和Sub/Add、Host分派、tiling、DMA字节/行间距。过去Q53裁剪、trueFMA残差、补偿累积合并、Gather、bank padding、positions缓存、手动mask、wide two-read及trig精度负结果都保留，未重试。

算法仍为K=D/2个频率、每token的K组角度及sin/cos，跨H个head复用，旋转3*N*H*D FLOPs。最低X/Y逻辑流量2*N*H*D*e，FP16/FP32旋转强度0.75/0.375 FLOP/B；频率、trig、转换、控制另计。positions是int32，合法范围可精确转FP32，不是第三种x/y类型。频率、角度和三角值继续在Device中生成，每次调用重新计算，没有Host输入计算、预存结果、跨调用缓存或计时外计算。

两个主要公开代表都为N1024/H64、2048个job、48核各42/43个job。核边界共访问1040次token而非理想1024，本轮不改变该分区，也不凭官方测试编号猜shape。基线在每个job末尾PIPE_ALL，两个半输入装载→向量工作→两个半输出写回依次进行。源绑定PMU显示FP16为VEC39.17/MTE236.42/MTE336.51us，FP32为52.96/77.15/61.13us（48核平均活跃时间，replay诊断），支持研究数据搬移与计算重叠。

只实现了以下两个中间版和一个最终版，补丁均保留：

| 版本 | 与谁比较 | 单项变化 | SHA前缀 |
|---|---|---|---|
| [direct](intermediates/direct/kernel.asc) | 817f8364 | FP32保留dense c/s，直接读VECIN、写VECOUT，去掉3次半输入及2次半输出UB拷贝；queue1、per-job PIPE_ALL保留，FP16不变 | 6f74f7f5 |
| [compact](intermediates/compact/kernel.asc) | direct | 仅FP16加入已测的紧凑系数和两半输入保留；FP32直接队列路径不变，queue1及屏障保留 | 5128bd8e |
| [pipeline](kernel.asc) | compact，以及817f8364 | 输入/输出各2槽，预取下一个job，以队列事件替代逐job全管线排空，保留最终drain；position0经输出队列写回 | f32e9651 |

copy-removal的源级流量模型以count=rows*pitch计：FP32每job移除5*count次元素复制，即5*count*8字节UB读写操作数流量。它没有减少GM逻辑流量，也没有改变dense系数展开。FP16中间版移除按head复制c/s及重复的第一半Cast，仍保留FP32旋转。API调用、硬件repeat体及实际指令数分开记录，未把count API的每个repeat误当独立指令。

direct的FP32 position0已经随输出队列改为按位复制并统一写回，保留job末尾drain；原分支在直接读VECIN发起MTE3前的额外全屏障由队列依赖代替。此时仍是queue1、逐job排空，没有稳态跨job流水。两个主要固定性能输入均无position0，所以该分支不影响本轮copy-removal的代表计时归因；所有零位置覆盖另外通过原身份位模式检查。

缓冲模型先于实现完成，见 [pre_experiment_model.json](pre_experiment_model.json)。cap=tileHeads*pitch。FP32两半原输入留在输入队列，两个结果直接在输出队列；工作区只有dense c、s、tmp共3*cap浮点元素。新token先将输出第一段用作angle，输出cap偏移处用作temp，tmp用作q，三角计算完成后才写旋转结果。cap>=pitch保证H=1时也互不覆盖。FP16保留a/b/lo/hi/tmp共5*cap浮点元素，c/s各一行位于频率缓冲尾部。

双缓冲FP32为44*cap字节加频率及必要fallback，FP16为36*cap字节加频率、紧凑c/s及fallback。全部合法偶数D/H组合的保守枚举上界分别182272B和153600B，低于188KiB。小head的频率fallback也计入；Scalar频率根缓存只有5个uint64，共40B。FP32工作区由5*cap减为3*cap会改变部分小head的频率chunk/fallback布局，频率函数和数学不变；两个主要性能代表均仍使用完整pitch。本轮没有隐瞒这一初始化调度差别，完整数值回归包含这些分支。

队列依赖按现有SDK及AlignedRotary/DirectFloatRotary协议逐项核对，相关头文件SHA在模型中：

- 输入EnQue设置MTE2_V，DeQue等待装载完成；最后一次输入读取后FreeTensor设置V_MTE2，槽位再次AllocTensor时等待，防止预取覆盖仍在计算的数据。
- 输出EnQue/DeQue建立V_MTE3依赖，写回完成后的FreeTensor建立MTE3_V，后续AllocTensor等待，防止输出或trig scratch覆盖尚在写回的槽位。
- position0将两半输入按位复制到VECOUT，统一经过输出队列事件及原strided stores，不再直接从VECIN发起MTE3。NaN/Inf/-0的身份位模式保留。
- begin==end时不预取；仅在job+1<end时预取下一job；没有最后一项多取、未消费的输入队列或零行job。每核末尾保留PIPE_ALL，排空最后一批写回。
- c/s/tmp和FP16工作区只由VEC顺序使用，MTE2写不同输入槽、MTE3读受保护输出槽；临时交叉积在使用后才覆盖。没有全局同步或跨核结果缓存。

使用原生非replay Task Duration、固定输入、同进程共享上下文与地址、ABBA及交换源码后的BAAB。每种源码取四个block中位数的中位数。比较结果不能跨不同测量进程简单相乘：

| 因果比较 | D126/H64 FP16 | D254/H64 FP32 | 固定33点几何平均 |
|---|---:|---:|---:|
| direct / 官方父版 | 1.0006x（未改路径） | 1.0585x | 1.00056x |
| compact / direct | 1.1110x | 1.0006x（未改路径） | 1.00564x |
| pipeline / compact | 1.5636x | 1.5935x | 1.02714x |
| pipeline / 官方父版 | **1.7253x** | **1.6801x** | **1.03324x** |

最终代表耗时分别108.7825→63.0515us（减少42.04%）、153.563→91.402us（减少40.48%），两种源码顺序都支持收益。小非对齐D24/H3/FP16为5.26→5.34us，增加1.52%，保留此回退而不追加路由特判。未改动entry的30个控制点几何平均1.00099x，范围0.9752–1.0152x；这些波动不计作本方案收益。

扩展性能集为公开构造的N257/H65、D66/126/254/514/1022、两种dtype，共10点，覆盖尾head与宽非对齐布局，均在两种源码顺序中加速，范围1.3121–1.9283x，几何平均1.50773x。不是官方隐藏点映射，也不等于所有合法shape都会同幅度加速。详见 [native_summary.json](native_summary.json) 及原始benchmarks/results和profiles中的全部block样本。

PMU补齐了FP32 direct和最终两种dtype，父版复用原817源码数据；FP16 compact仅复用已证明执行入口字节相同的d655 PMU，未篡改其原source metadata。绑定证明见 [compact_half_PMU_reuse.json](compact_half_PMU_reuse.json)。

| PMU的48核平均活跃时间/us | FP16 compact→pipeline | FP32 direct→pipeline |
|---|---:|---:|
| elapsed | 109.699→66.705 | 193.548→117.109 |
| VEC | 26.847→25.786 | 43.898→43.896 |
| MTE2 | 37.728→59.506 | 77.683→108.952 |
| MTE3 | 37.315→45.926 | 60.957→62.465 |

三个管线活跃时间之和/elapsed从约0.93/0.94变为1.97/1.84，配合源级事件链，支持工作从串行转为重叠。单个MTE活跃时间会因同时争用端口而变长，不能把阶段耗时直接相加预测最终时间，也不能把VEC busy当有效lane或峰值算力利用率。scalar_vector_stall也不能直接叫“空跑”。没有分离测得精确frequency/trig初始化时间，没有声称DRAM峰值；正式收益只用原生配对计时，见 [pmu_comparison.json](pmu_comparison.json)。

安装的反汇编器不能解码本设备HiIPU，未为此安装工具或重复失败探针。采用SDK事件映射、源码API/布局和嵌入entry字节审计：direct仅改4个FP32入口，compact相对direct仅改4个FP16入口，最终相对父版只改8个通用Rotary入口，其他36个完全一致。普通/audit构建的44个入口完全一致，原模板C++14构建与已验证普通构建的44个入口也全部一致，不编造实际汇编指令计数。

每份新源码都完成1723项验证：复用原1625项冻结输入、golden、817父输出及其已提交哈希，新增98项独立父输出；没有重复测量旧父数据。新增集包含1/49/257 token、1/33/65 head、全零/交替零/尾零、1025-token长循环、窄和宽非对齐。每份源码均满足：

- 1723/1723完整输出逐位相同；1722项通过原阈值，冻结大幅值FP16仍失败，双方max32，matched_ratio=0.9999874208351224。没有修改golden、阈值或筛掉失败。
- guard、position0的NaN/Inf/-0身份位模式、逐调用单启动均通过。每份新源码审计1919次调用（三份共5757次）；新增98项父控制另有294次审计。
- 原生配对实验11360次调用对应11360个设备任务；独立检查75/75通过。计时的固定33+额外10项最终完整输出也均与817父版逐字节相同。
- 原模板C++14/dav-2201构建成功，7个支持文件逐字节不变，仅替换kernel.asc；无新库、生成辅助文件、额外包或CMake/link改动。NumPy只在离线诊断中使用。

原始分类与全部失败记录分别在 [direct](direct_correctness.json)、[compact](compact_correctness.json)、[pipeline](pipeline_correctness.json)；[validate.py](validate.py)复用未改动的原compare/generate逻辑。[combine.py](combine.py)只离线合并原profile_paired输出，不改变计时采样。20项NPU任务均经现有task-submit串行申请单卡、max-time60，已经结束并释放设备。编译和准备均在预约外完成。

结论是性能假设得到支持，生产ready仍因继承精度限制blocked。任务要求的一个最终实验候选及两份中间证据已经归档，可以交主控审阅是否执行一次真实平台试验；不能将本地比值作为新官方分数或宣称普遍精度通过。正式源码、latest、旧closed response、规则和参考文件保持原哈希。到此停止，不再改源码、不再运行NPU任务，等待下一条主控通知。
