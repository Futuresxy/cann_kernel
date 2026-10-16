# 平台编译报错与完整源码交付

本次用户提供了平台实际kernel源码：第一行是`auto input=in_.DeQue<T>();if(job+1<end)Prefetch(job+1);`，最后是`// END_ROPE1743_V3`。第一行对应仓库完整源码第353行，缺少前352行，包括头文件、namespace、类型、辅助函数、三条执行路径的定义和当前循环的外层作用域。

本地以原始8文件模板分别构建两个输入：

- 只保留完整源码第353行至末尾：复现平台的`kernel.asc:1:34`未声明T、`:1:24`未声明in_、`:1:28`missing template等错误。
- 恢复完整471行：原始CMake配置编译通过。missing template是外层定义缺失后的连带错误，不应通过在DeQue前加关键字来处理。

完整源文件SHA256为`ee0613601ab08a72d401203035bf2ab7b9c4b08fa04f332eb39a7518ddd77130`，23153字节。首行是`// ROPE1743_SINGLE_LAUNCH_V3`，末行是`// END_ROPE1743_V3`。首尾标记、长度与哈希一起用于核对交付；仅有末尾标记不足以说明前文存在。

单卡任务`task_20261015_175641_154005811813`在物理卡0、60秒上限内通过原模板公开样例、37项代表集、1010项全偶数维度扫描、2242次逐次调用启动检查、75次调用/75个设备kernel任务及一次PMU采集，exit=0并释放设备。原模板公开样例最大绝对误差2.6226043701171875e-6。PMU Task Duration为29.681 us；未将不同采样批次的波动计作新的算法优化。

算法源码保持已通过精度与单次启动约束的完整版。修复提交内容的方式是用完整文件替换平台中的片段。

## 提交文件

打包器生成以下包外辅助产物，内容均与已验证kernel字节一致：

- `dist/kernel.asc`：可直接提交的完整源码。
- `dist/kernel_full_source.txt`：完整纯文本，供需要粘贴代码的编辑器使用。
- `dist/kernel_upload.zip`：只含一个kernel.asc的下载压缩包。
- `dist/manifest.json`：SHA256、总字节数、总行数、首行与末行。

正式工程目录`dist/rotaryposemb_1743_submission/`与正式ZIP仍只有原模板8文件，仅kernel.asc改变；其余7个文件逐字节保留，不把纯文本、元数据或测试工具放入正式工程。

复测结果见`benchmarks/results/restored_full_v3*.json`，启动次数原始CSV见`benchmarks/profiles/restored_full_v3_launches`，PMU见`benchmarks/profiles/restored_full_v3`。
