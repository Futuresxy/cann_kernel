# 平台15点配置：原始公开资料核查

目前**尚未重建15点的shape/dtype/theta**。原始下载工程确实暴露配置，但只有一组可执行本地用例和一组不同的手工示例；它们与平台编号的对应关系未证实。题面另有三个明确示例，也没有公开平台编号映射。不得用耗时、平台点号或本地负载矩阵补齐未知项。

此次只读核查，没有新NPU任务、性能候选、平台提交、原脚本执行、环境修改、探针输出、故意报错或judge/计时干预。Mac主控负责已登录的正常结果页，本端未操作浏览器。此前shared-math诊断已归档为完成且有明确限制，四项既有任务均exit0并释放卡，52次启动审计与全部负结果保留；不领取排队的频率/实现请求。

## 可追溯原件

用户附件`rotaryposemb_problem_1743_template.zip`的SHA256为：

`8fcc24c896aa275deb35a8c1a6ef65bb4a9e20842b5ead80d88671c64e9ce94e`

直接用ZIP读取，**8个非目录成员均与仓库templates/rotaryposemb_1743逐字节一致**，并匹配原有SHA清单。ZIP仅有CMakeLists.txt、data_utils.h、kernel.asc、main.asc、run.sh和scripts中的gen_data.py、RotaryPosEmb.py、verify_result.py，没有任何JSON或15点配置清单。没有解压覆盖工作区，也没有执行run.sh或数据生成脚本。

[机器可读溯源](../benchmarks/analysis/public_case_metadata_20261017/provenance.json)包含附件绝对路径、ZIP与各成员SHA、AST列表长度、行号、原normal-result导出SHA，以及15行全部保留未知shape的矩阵。[CPU审计脚本](../benchmarks/analysis/public_case_metadata_20261017/audit.py)只解析原文件，不导入/执行其代码。

## 已知配置及证据等级

| 来源 | x shape / dtype | positions | theta | 原文位置 | 与平台15点关系 |
|---|---|---|---:|---|---|
| 原ZIP实际本地case0 | [1,7,1,16] / FP32 | [1,7] int32；randint [0,50)，seed42 | 10000 | gen_data.py:17–30；main.asc:48–58 | 未证实平台编号 |
| 原ZIP手工列表literal id=1 | [1,3,2,20] / FP32 | [1,3] int32；randint [0,3)，未显式设置seed | 10000 | RotaryPosEmb.py:48–60 | 仅源码literal id，不能直接映射平台第1点 |
| 用户所贴题面示例1 | [1,8,1,16] / FP32 | [1,8] int32；连续0..7 | 10000 | 原始题面附件:148–153 | 题面示例，平台编号未知 |
| 用户所贴题面示例2 | [2,512,128,64] / FP16 | [2,512] int32；随机[0,8192) | 10000 | 原始题面附件:155–160 | 题面示例，平台编号未知 |
| 用户所贴题面示例3 | [2,16,3,24] / FP16 | [2,16] int32；分布未说明 | 10000 | 原始题面附件:162–167 | 题面示例，平台编号未知 |

第一行同时得到main的448字节x/y、28字节positions分配与生成脚本支持。verify_result.py也只有key0输出配置；run.sh只复制input/case0与golden_case0并运行该main。这是原模板实际执行的本地用例。

第二行需要单独标识：`RotaryPosEmb.py:49`注释写“与JSON npu_cases对应的15个测试用例”，但AST确认`cases`列表**实际只有1项**，即line52的`(1,[1,3,2,20],np.float32,3,10000.0)`。其主程序直接生成该项，没有读取JSON；gen_data.py只是import其impl函数，不执行这个手工列表。注释不是完整15点元数据，literal id=1也不等于验证过的平台第1项。

题面小样本S8与可执行模板S7、手工示例S3是三个不同来源的配置。保留差异，不统一改写或混淆。

## 平台编号仍未恢复

仓库已有883390等normal-result精简导出包含编号、Pass/错误比例、耗时与当时最优耗时；不含shape/dtype/theta/positions。883390的15条记录已逐条检查这些字段缺失。其编号与耗时可保留，但**当前0/15条有经证实的输入配置映射**。本地tests/*.json为开发阶段自行设计的覆盖集，不能作为官方用例清单。

公开题面URL的普通Web读取本次返回“不可访问”，没有取得新页面内容，也没有尝试私有接口、参数枚举或认证信息。本文题面信息明确取自用户当初提供的原始文本，未声称是最新网页导出。

下一步只等待Mac主控从正常可见页面/原始下载项目取得明确的配置、编号和出处；若有新原件，先核对下载时间/哈希与该旧ZIP差异，再追加已证实字段。不能从48.78分或15点耗时唯一反推出形状；不得据此做用例专属dispatch、标记、故意错误或计时干预。

[诊断归档与暂停状态](../benchmarks/analysis/public_case_metadata_20261017/diagnostic_hold.json)记录全部既有任务已结束、继承FP16 max_abs_error32未修复、当前无新增测量/候选。本次核查的结论是公开元数据已分类，15点完整配置仍待可验证来源。

## 主控交叉核对补充

合并主控提交`7873d81`后，已读取[正常题目页元数据导出](../benchmarks/analysis/platform_case_metadata_partial.json)：15行按序case_ID为11471–11485，shape/dtype/theta/positions均为空。该身份映射来自Mac正常已登录题目页响应，本端只读取Git归档，没有自行请求其接口。机器可读矩阵已追加case_ID与出处，同时继续保留全部输入配置未知。Mac核对的下载ZIP SHA与本端附件完全一致。主控暂停交接已保留，不启动后续任务或自动化监听。
