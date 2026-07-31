# 视频字幕 → RAG观点卡片 完整工具链

## 文件说明

| 文件 | 作用 |
|------|------|
| `subtitle_to_rag.py` | **核心提取器**：单文件处理，输入 `.srt/.vtt`，输出结构化观点卡片JSON |
| `batch_process.py` | **批量处理**：扫描目录下所有字幕，自动批量提取并合并 |
| `vector_store.py` | **向量库+对话**：将JSON写入Chroma向量库，支持检索和对话 |

## 完整工作流

```
字幕文件(.srt/.vtt)
    │
    ▼  subtitle_to_rag.py 或 batch_process.py
观点卡片JSON (rag_chunks.json)
    │
    ▼  vector_store.py ingest
Chroma向量库
    │
    ▼  vector_store.py chat
对话Agent（带引用溯源）
```

## 快速开始

### 1. 安装依赖

```bash
pip install pydantic openai chromadb sentence-transformers
```

### 2. 单文件提取

```bash
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.moonshot.cn/v1"

python subtitle_to_rag.py \
    --input "长鑫科技.srt" \
    --output chunks.json \
    --title "长鑫科技，荣登A股第一市值" \
    --up "职业炒股者" \
    --model kimi-latest
```

### 3. 批量提取

```bash
python batch_process.py \
    --dir ./subtitles \
    --output all_chunks.json \
    --model kimi-latest
```

### 4. 写入向量库

```bash
python vector_store.py ingest \
    --input all_chunks.json \
    --db ./chroma_db \
    --collection video_opinions
```

### 5. 检索测试

```bash
python vector_store.py search "长鑫科技为什么跳水" --n 5
```

### 6. 对话

```bash
python vector_store.py chat "UP主对长鑫后市的判断是什么？" \
    --model kimi-latest \
    --api-key $OPENAI_API_KEY
```

## 核心设计

### 观点卡片 Schema

每个chunk包含：
- `content`: 清洗后的完整陈述
- `content_type`: 观点/事实/预测/叙事/情感/方法论...
- `argument_role`: 主论点/子论点/论据/结论/让步/个人经验...
- `core_topic`: 核心主题
- `sub_topics`: 子主题标签
- `stance_type`: 支持/反对/中立/预测/判断/建议
- `confidence`: 强/中/弱/未论证
- `verifiability`: 可验证/待验证/不可验证/主观经验
- `source_type`: UP主本人/引用他人
- `original_arguments`: 支撑论据列表
- `time_position`: 精确时间戳（用于溯源）

### 检索增强策略

1. **文本增强**：写入向量库时，把 `core_topic`、`stance_type`、`argument_role` 拼接到content中，让向量检索更精准
2. **Metadata过滤**：支持按UP主、立场、类型、时间等维度过滤
3. **结构化Prompt**：对话Agent强制要求标注来源、区分事实与观点、并列冲突观点

## 自定义扩展

### 修改停顿阈值

默认 `pause_threshold=2.5` 秒，即两条字幕间隔超过2.5秒视为话题切换。口语快的UP主可调到1.5，慢的可调到4.0。

### 添加UP主映射

在 `batch_process.py` 中，可以从文件名或外部CSV读取UP主名称：

```python
UP_NAME_MAP = {
    "科技袁人_001.srt": "科技袁人",
    "老高与小茉_002.srt": "老高与小茉",
}
```

### 换Embedding模型

在 `vector_store.py` 中修改：

```python
self.embedder = SentenceTransformer('BAAI/bge-large-zh-v1.5')
# 或换成其他中文模型
```

## 注意事项

1. **LLM成本**：每个话题段调用一次LLM API。一个10分钟视频约10-20个话题段，费用可控。
2. **口误修正**：System Prompt中已内置常见口误修正指令（如"长信"→"长鑫"），可在 `SYSTEM_PROMPT` 中扩展。
3. **隐私**：字幕文本可能包含敏感信息，向量库建议本地部署（Chroma PersistentClient）。
