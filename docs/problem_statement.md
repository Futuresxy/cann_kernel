# 初赛】RotaryPosEmb算子

## 一、赛题背景

旋转位置编码（Rotary Position Embedding，RoPE）是现代大语言模型注入位置信息的核心机制，被 Llama、Qwen、DeepSeek、GLM 等主流模型广泛采用。RoPE 将 token 向量的维度配对为二维平面上的点，并按"频率 × 位置"的角度对每对维度做旋转，从而在不引入可学习参数的前提下编码相对位置关系。

本题要求基于 PyTorch 中旋转位置编码的核心业务逻辑，采用 Ascend C 编程语言进行算子原生开发，在昇腾 NPU 硬件上实现一款高性能的 RotaryPosEmb 算子。

## 二、算子功能描述

实现的 RotaryPosEmb 算子需完成以下核心计算：

1. 根据维度与 theta 计算逆频率 `inv_freq[i] = 1 / theta^(2i/dim)`
2. 由位置索引与逆频率生成旋转角，进而计算 cos/sin
3. 对输入张量施加旋转位置编码：将 x 的最后一维配对后按对应旋转角旋转，得到输出 y

算子输入的 x 为解耦出来的位置编码子维度（rope 部分），只对 rope_dim 做旋转。

## 三、核心定义与约束

### 3.1 参考算子

PyTorch 中旋转位置编码的一种等价实现如下。旋转的具体实现方式（rotate-half、复数乘法或其他数学等价方法）不限，以下实现仅用于说明数学逻辑：

```
import torch


def apply_rotary_pos_emb(x, positions, theta):
    dim = x.shape[-1]
    # 1. 逆频率
    inv_freq = 1.0 / (theta ** (torch.arange(0, dim, 2)[: dim // 2].float() / dim))

    # 2. 旋转角与 cos/sin
    freqs = positions.float().unsqueeze(-1) * inv_freq      # [B, S, dim/2]
    theta_freqs = torch.cat([freqs, freqs], dim=-1)          # [B, S, dim]
    cos = torch.cos(theta_freqs).unsqueeze(2)                # [B, S, 1, dim]
    sin = torch.sin(theta_freqs).unsqueeze(2)

    # 3. rotate-half 旋转
    def rotate_half(t):
        t1, t2 = t[..., : dim // 2], t[..., dim // 2 :]
        return torch.cat((-t2, t1), dim=-1)

    return x * cos + rotate_half(x) * sin
```



### 3.2 数学公式

设输入 `x` 的最后一维为 `dim`（rope_dim），位置索引为 `p`（来自 positions），基础逆频率：

inv_freq[i]=θ−2i/dim,i=0,1,…,dim/2−1inv_freq[*i*]=*θ*−2*i*/dim,*i*=0,1,…,dim/2−1

旋转角与三角函数：

Θ[b,s]=concat( p[b,s]⋅inv_freq[i], p[b,s]⋅inv_freq[i] )Θ[*b*,*s*]=concat( *p*[*b*,*s*]⋅inv_freq[*i*], *p*[*b*,*s*]⋅inv_freq[*i*] )

cos=cos⁡(Θ),sin=sin⁡(Θ)cos=cos(Θ),sin=sin(Θ)

旋转位置编码（x 的最后一维分成前后两半，前 dim/2 维与后 dim/2 维两两配对，第 i 对共享旋转角 θi=p[b,s]⋅inv_freq[i]*θ**i*=*p*[*b*,*s*]⋅inv_freq[*i*]）：

y[…,i]=x[…,i]cos⁡θi−x[…,i+dim/2]sin⁡θi*y*[…,*i*]=*x*[…,*i*]cos*θ**i*−*x*[…,*i*+dim/2]sin*θ**i*

y[…,i+dim/2]=x[…,i+dim/2]cos⁡θi+x[…,i]sin⁡θi*y*[…,*i*+dim/2]=*x*[…,*i*+dim/2]cos*θ**i*+*x*[…,*i*]sin*θ**i*

其中 i=0,1,…,dim/2−1*i*=0,1,…,dim/2−1。旋转的具体实现方式不限，任何数学等价方法（如 rotate-half、复数乘法等）均可。

### 3.3 输入输出与属性总览

| 类型         | 参数名    | 类型   | 维度形状            | 支持数据类型     | 数据格式  | 备注                            |
| ------------ | --------- | ------ | ------------------- | ---------------- | --------- | ------------------------------- |
| INPUT(必选)  | x         | tensor | (B, S, H, rope_dim) | float16, float32 | ND        | 待旋转的 rope 子维度张量        |
| INPUT(必选)  | positions | tensor | (B, S)              | int32            | ND        | 每个 token 的位置索引           |
| ATTR(属性)   | theta     | float  | -                   | -                | -         | RoPE 基础频率基数，默认 10000.0 |
| OUTPUT(输出) | y         | tensor | 与 x 一致           | 与 x 一致        | 与 x 一致 | 旋转位置编码后的输出            |

### 3.4 关键输入约束

- **数据类型**: float16, float32
- **维度场景**: 4维输入（B, S, H, rope_dim），B 为 batch，S 为序列长度，H 为头数，rope_dim 为位置编码维度
- **维度取值范围（均为正整数）**:
  - B（batch）: [1, 128]
  - S（序列长度）: [1, 8192]
  - H（头数）: [1, 256]
  - rope_dim（位置编码维度）: [16, 1024]，且必须为偶数
- **位置索引约束**: positions 中每个元素为 [0, 131072] 的整数，表示绝对位置
- **典型 shape**:
  - DeepSeek V3 实际场景: (B, S, 128, 64)，rope_dim=64，128 个 head
  - 小规模调试: (1, 8, 1, 16)
- **非对齐场景**: rope_dim、H、S 的任意组合可能导致非对齐的内存访问，算子需正确处理

### 3.5 核心属性说明

- **theta**（float，默认 10000.0）: RoPE 的几何级数基数，决定各维度频率的分布范围

### 3.6 输出严格要求

- **形状约束**: y.shape == x.shape，所有维度尺寸不变
- **类型约束**: y 的数据类型与 x 一致
- **数值等价**: 输出与 PyTorch 参考实现在合理浮点误差范围内一致
- **中间精度要求**: inv_freq 计算、三角函数 cos/sin 生成必须使用 FP32 精度，避免长序列下角度误差累积

### 3.7 特殊值处理规则

- **NaN/Inf 输入**: 输入含 NaN/Inf 时，输出对应位置为 NaN/Inf，算子不应崩溃
- **位置为 0**: positions 为 0 时，cos=1、sin=0，输出 y == x（旋转角为 0）
- **rope_dim 边界**: rope_dim 为偶数，旋转配对的前后两半各为 dim/2 维

## 四、规则要求

1. **cos/sin 生成规则**: 逆频率计算与三角函数 cos/sin 的生成在算子内部完成，cos/sin 不作为算子输入
2. **实现方式规则**: 旋转位置编码的具体实现方式不限（如 rotate-half、复数乘法等），任何与数学定义等价的实现均可
3. **中间精度规则**: 逆频率与三角函数计算必须使用 FP32 精度，旋转乘法可在输入精度下进行，需保证最终输出与 golden 的误差在阈值内

## 五、精度判断规则

以更高精度的参考实现结果作为 golden（标杆）进行逐元素比较。

**逐元素通过条件**：`abs(actual - golden) <= atol + rtol * abs(golden)`，其中 `atol` 为绝对误差，`rtol` 为相对误差。

**整体通过条件**：通过率 `matched_ratio = 通过元素数 / 总元素数`，当同时满足以下条件时判定用例通过：

1. `matched_ratio >= required_matched_ratio`
2. `max_abs_error <= max_abs_error_limit`（`max_abs_error` 为任意元素的最大绝对误差）

**误差阈值表**：

| 数据类型               | float32 | float16 | bfloat16 |
| ---------------------- | ------- | ------- | -------- |
| atol                   | 9.77e-4 | 1.95e-3 | 1.56e-2  |
| rtol                   | 1.53e-5 | 1.95e-3 | 1.56e-2  |
| required_matched_ratio | 0.99    | 0.99    | 0.99     |
| max_abs_error_limit    | 1e-2    | 1e-1    | 1e-0     |

## 六、得分规则

- 本次比赛共15个测试点，所有case点精度全部通过才会计分。
- 每个测试点单独计分，逻辑如下（T为最优性能，t为当前提交性能）：

1001+log⁡1.5tT1+log1.5*T**t*100

- 排行榜显示的最终分数为所有case得分的均值。若得分计算一致，则以提交时间进行排序，提交越早，排名越高。

## 七、示例说明

**示例1**: 极小规模调试

- 输入 x: shape=[1, 8, 1, 16], dtype=float32
- positions: shape=[1, 8], 值为 0~7 的连续位置
- 属性: theta=10000.0
- 输出 y: shape=[1, 8, 1, 16]，为 x 按各自位置旋转后的结果

**示例2**: DeepSeek V3 实际场景

- 输入 x: shape=[2, 512, 128, 64], dtype=float16
- positions: shape=[2, 512]，值为 [0, 8192) 的随机位置
- 属性: theta=10000.0
- 输出 y: shape=[2, 512, 128, 64]

**示例3**: 非对齐 rope_dim

- 输入 x: shape=[2, 16, 3, 24], dtype=float16（rope_dim=24 非 2 的幂）
- positions: shape=[2, 16]
- 属性: theta=10000.0
- 输出 y: shape=[2, 16, 3, 24]