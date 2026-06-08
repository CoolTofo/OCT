# W Project HOLO API Reference
# W Project HOLO API 接口文档

**Version / 版本:** v1.5 (2026-05-08)
**Base URL / 基础地址:** `https://api.dealonhorizon.us`

---

## Authentication / 认证

All requests require an API key via header:
所有请求需要通过请求头传递 API Key：

```
Authorization: Bearer YOUR_API_KEY
```
or / 或
```
X-API-Key: YOUR_API_KEY
```

---

## Quick Guide / 快速选择

| Task / 任务 | Endpoint / 接口 | Note / 说明 |
|---|---|---|
| Generate 1 image / 生成单张图片 | `POST /v1/generate` | Async, poll for result / 异步，轮询结果 |
| Reference-to-Image / 参考生图 | `POST /v1/generate` | Same model + image_url → auto R2I / 同模型名+图片自动识别 |
| Generate 1 video / 生成单个视频 | `POST /v1/generate` | Same endpoint / 同一接口 |
| Check result / 查询结果 | `GET /v1/tasks/{id}` | Poll every 5-10s / 每5-10秒轮询 |
| Download file / 下载文件 | `GET /v1/tasks/{id}/file` | 24h retention / 保留24小时 |
| List tasks / 任务列表 | `GET /v1/tasks` | Filter by status / 按状态过滤 |
| Account info / 账户信息 | `GET /me` | Balance, usage / 余额和使用量 |

> **All generation (image + video) uses `POST /v1/generate`**, one request per image or video.
>
> **所有生成（图片+视频）统一使用 `POST /v1/generate`**，每次生成一张图片或一个视频。

---

## Endpoints / 接口列表

### 1. Submit Generation Task / 提交生成任务

`POST /v1/generate`

Submit an image or video generation task. Returns immediately with a task ID.
提交图片或视频生成任务，立即返回 task_id，通过轮询获取结果。

**Request — Text-to-Image / 文字生图:**
```json
{
  "model": "gemini-3.0-pro-image-landscape",
  "messages": [
    {"role": "user", "content": "A blue butterfly on a flower"}
  ]
}
```

**Request — Text-to-Image Square / 文字生图 方形:**
```json
{
  "model": "gemini-3.1-flash-image-square",
  "messages": [
    {"role": "user", "content": "A minimalist logo design with geometric shapes"}
  ]
}
```

**Request — Text-to-Image 4:3 / 文字生图 4:3:**
```json
{
  "model": "gemini-3.0-pro-image-four-three-2k",
  "messages": [
    {"role": "user", "content": "A cinematic still of a cyberpunk city at night"}
  ]
}
```

**Request — Reference-to-Image / 参考生图 (R2I):**

> R2I uses the same image model name — when `image_url` is included in the request, it is automatically detected as R2I and billed at R2I pricing.
>
> R2I 使用同样的图片模型名 — 请求中包含 `image_url` 时自动识别为 R2I，按 R2I 价格计费。

```json
{
  "model": "gemini-3.0-pro-image-landscape",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/reference.jpg"}},
      {"type": "text", "text": "Generate a similar image with autumn colors"}
    ]}
  ]
}
```

**Request — Reference-to-Image 2K / 参考生图 2K:**
```json
{
  "model": "gemini-3.1-flash-image-square-2k",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/style-ref.jpg"}},
      {"type": "text", "text": "Recreate this composition with a watercolor painting style"}
    ]}
  ]
}
```

**Request — Reference-to-Image 4K / 参考生图 4K:**
```json
{
  "model": "gemini-3.0-pro-image-portrait-4k",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ..."}},
      {"type": "text", "text": "A portrait in the same style but with different lighting"}
    ]}
  ]
}
```

**Request — GPT-images2 (Text-to-Image) / GPT-images2 文生图:**
```json
{
  "model": "GPT-images2 16:9-4K",
  "messages": [
    {"role": "user", "content": "A cinematic wide shot of a cyberpunk city at dusk"}
  ]
}
```

> Model name contains a space — pass it verbatim. Use `GPT-images2` for default (1024×1024), or `GPT-images2 {variant}` to choose a specific size variant (see model table below).  
> 模型名包含空格，请原样传递。`GPT-images2` 默认 1024×1024，`GPT-images2 {variant}` 指定具体尺寸（见下方模型表）。

**Request — GPT-images2 (Reference-to-Image) / GPT-images2 参考生图:**
```json
{
  "model": "GPT-images2 1:1",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/reference.jpg"}},
      {"type": "text", "text": "Turn this into a vintage comic book style illustration"}
    ]}
  ]
}
```

**Request — Text-to-Video / 文字转视频:**
```json
{
  "model": "veo_3_1_t2v_fast_landscape",
  "messages": [
    {"role": "user", "content": "A drone shot flying over a tropical island"}
  ]
}
```

**Request — Image-to-Video / 图片转视频 (I2V):**
```json
{
  "model": "veo_3_1_i2v_fast_landscape",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}},
      {"type": "text", "text": "Slowly zoom in with gentle camera movement"}
    ]}
  ]
}
```

> **First + Last Frame Mode / 首尾帧模式 (auto / 自动):**
> When you send **2 image_urls** with an i2v model, the system automatically switches to first-last-frame video generation — the first image is the starting frame, the second is the ending frame, and the video is interpolated between them. **No special model name needed**, just pass two images to any i2v model.  
> 当你给 i2v 模型传 **2 张 image_url** 时，系统自动切换到首尾帧视频生成 — 第一张作为起始帧，第二张作为结束帧，中间动画自动插值生成。**不需要切换模型名**，给任何 i2v 模型传 2 张图即可。

**Request — First + Last Frame I2V / 首尾帧图片转视频 (i2v + 2 张图自动触发):**
```json
{
  "model": "veo_3_1_i2v_fast_portrait",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/start.jpg"}},
      {"type": "image_url", "image_url": {"url": "https://example.com/end.jpg"}},
      {"type": "text", "text": "Smooth morph transition between the two frames"}
    ]}
  ]
}
```

**Request — Text-to-Video Quality / 文字转视频 高质量:**
```json
{
  "model": "veo_3_1_t2v_landscape",
  "messages": [
    {"role": "user", "content": "A cinematic sunset over the ocean with volumetric clouds"}
  ]
}
```

**Request — Text-to-Video Quality 1080p / 文字转视频 高质量 1080p:**
```json
{
  "model": "veo_3_1_t2v_landscape_1080p",
  "messages": [
    {"role": "user", "content": "A cinematic aerial shot of a mountain range at golden hour"}
  ]
}
```

**Request — Text-to-Video Quality 4K / 文字转视频 高质量 4K:**
```json
{
  "model": "veo_3_1_t2v_portrait_4k",
  "messages": [
    {"role": "user", "content": "A vertical cinematic shot of a waterfall in a lush forest"}
  ]
}
```

**Request — Image-to-Video Quality / 图片转视频 高质量:**
```json
{
  "model": "veo_3_1_i2v_s_landscape",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}},
      {"type": "text", "text": "Gentle parallax movement with cinematic depth of field"}
    ]}
  ]
}
```

**Request — Image-to-Video Quality 1080p / 图片转视频 高质量 1080p:**
```json
{
  "model": "veo_3_1_i2v_s_landscape_1080p",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/start.jpg"}},
      {"type": "text", "text": "Cinematic dolly zoom with bokeh background"}
    ]}
  ]
}
```

**Request — Image-to-Video Quality 4K (first + last frame) / 图片转视频 高质量 4K (首尾帧):**
```json
{
  "model": "veo_3_1_i2v_s_portrait_4k",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/start.jpg"}},
      {"type": "image_url", "image_url": {"url": "https://example.com/end.jpg"}},
      {"type": "text", "text": "Character turns around slowly, background transitions to night"}
    ]}
  ]
}
```

> 2 image_urls 自动触发首尾帧,1 张图即标准 i2v / Two image_urls trigger first-last-frame mode automatically; one image is standard i2v.

**Request — Reference-to-Video / 参考转视频 (R2V):**

> R2V (`veo_3_1_r2v_*`) uses up to 3 images as **style references** (not start/end frames). The video is generated freshly with the references guiding overall look. This is different from i2v + 2 images (first-last-frame mode above).  
> R2V (`veo_3_1_r2v_*`) 把图作为**风格参考**（最多 3 张），视频从头生成，参考图只引导整体风格。这与 i2v + 2 张图（首尾帧）不同。

```json
{
  "model": "veo_3_1_r2v_fast_landscape",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/ref1.jpg"}},
      {"type": "image_url", "image_url": {"url": "https://example.com/ref2.jpg"}},
      {"type": "text", "text": "Generate a video using these reference images as style guide"}
    ]}
  ]
}
```

**Request — Text-to-Video Lite / 文字转视频 轻量:**
```json
{
  "model": "veo_3_1_t2v_lite_landscape",
  "messages": [
    {"role": "user", "content": "A cat walking through a sunny garden"}
  ]
}
```

**Request — Image-to-Video Lite / 图片转视频 轻量:**
```json
{
  "model": "veo_3_1_i2v_lite_portrait",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}},
      {"type": "text", "text": "Animate with gentle floating motion"}
    ]}
  ]
}
```

> Lite models are faster and cheaper than Fast, ideal for previews and high-volume use.
> Lite 模型比 Fast 更快更便宜，适合预览和大批量使用。

**Request — Text-to-Image 2K / 文字生图 2K:**
```json
{
  "model": "gemini-3.0-pro-image-landscape-2k",
  "messages": [
    {"role": "user", "content": "A beautiful sunset over mountains in high detail"}
  ]
}
```

**Request — Text-to-Image 4K / 文字生图 4K:**
```json
{
  "model": "gemini-3.0-pro-image-portrait-4k",
  "messages": [
    {"role": "user", "content": "A portrait of a woman in oil painting style, ultra detailed"}
  ]
}
```

**Request — Text-to-Video 1080p / 文字转视频 1080p:**
```json
{
  "model": "veo_3_1_t2v_fast_landscape_1080p",
  "messages": [
    {"role": "user", "content": "A timelapse of clouds moving over a city skyline"}
  ]
}
```

**Request — Text-to-Video 4K / 文字转视频 4K:**
```json
{
  "model": "veo_3_1_t2v_fast_portrait_4k",
  "messages": [
    {"role": "user", "content": "A vertical video of rain falling on a window"}
  ]
}
```

**Request — I2V 1080p / 图片转视频 1080p:**
```json
{
  "model": "veo_3_1_i2v_fast_landscape_1080p",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/start.jpg"}},
      {"type": "text", "text": "Slowly zoom in with cinematic depth of field"}
    ]}
  ]
}
```

**Request — I2V 4K / 图片转视频 4K:**
```json
{
  "model": "veo_3_1_i2v_fast_portrait_4k",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ..."}},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4BBR..."}},
      {"type": "text", "text": "Character slowly turns around, background blurs"}
    ]}
  ]
}
```

**Request — R2V 1080p / 参考转视频 1080p:**
```json
{
  "model": "veo_3_1_r2v_fast_landscape_1080p",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/ref.jpg"}},
      {"type": "text", "text": "Create a cinematic video based on this reference"}
    ]}
  ]
}
```

**Request — R2V 4K / 参考转视频 4K:**
```json
{
  "model": "veo_3_1_r2v_fast_portrait_4k",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/ref1.jpg"}},
      {"type": "image_url", "image_url": {"url": "https://example.com/ref2.jpg"}},
      {"type": "image_url", "image_url": {"url": "https://example.com/ref3.jpg"}},
      {"type": "text", "text": "Generate a vertical 4K video using these references as style guide"}
    ]}
  ]
}
```

> Quality models produce higher fidelity output but take longer to generate.
> Quality 模型生成质量更高，但耗时更长。

---

#### Duration Variants & R2V Lite / 时长选项 + R2V 轻量

**Request — T2V 4 seconds Fast / 文字转视频 4 秒 快速:**
```json
{
  "model": "veo_3_1_t2v_fast_4s_landscape",
  "messages": [
    {"role": "user", "content": "A drone flyover of a tropical island"}
  ]
}
```

**Request — T2V 6 seconds Quality / 文字转视频 6 秒 高质量:**
```json
{
  "model": "veo_3_1_t2v_quality_6s_portrait",
  "messages": [
    {"role": "user", "content": "Cinematic close-up of raindrops falling on glass"}
  ]
}
```

**Request — T2V 4 seconds Lite / 文字转视频 4 秒 轻量:**
```json
{
  "model": "veo_3_1_t2v_lite_4s_landscape",
  "messages": [
    {"role": "user", "content": "Quick preview: a bird flying across a blue sky"}
  ]
}
```

**Request — T2V 6 seconds Lite / 文字转视频 6 秒 轻量 (highest-volume preview use case / 大批量预览常用):**
```json
{
  "model": "veo_3_1_t2v_lite_6s_portrait",
  "messages": [
    {"role": "user", "content": "Vertical preview: ocean waves at sunset"}
  ]
}
```

**Request — I2V 4 seconds Fast / 图片转视频 4 秒 快速:**
```json
{
  "model": "veo_3_1_i2v_fast_4s_portrait",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/portrait.jpg"}},
      {"type": "text", "text": "Subtle head turn with hair flowing"}
    ]}
  ]
}
```

**Request — I2V 6 seconds Quality / 图片转视频 6 秒 高质量:**
```json
{
  "model": "veo_3_1_i2v_quality_6s_landscape",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/scene.jpg"}},
      {"type": "text", "text": "Camera slowly pulls back revealing the wider scene"}
    ]}
  ]
}
```

**Request — R2V Lite / 参考转视频 轻量 (新档, 720p only, 8s):**
```json
{
  "model": "veo_3_1_r2v_lite_landscape",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/ref.jpg"}},
      {"type": "text", "text": "Cinematic motion based on this reference"}
    ]}
  ]
}
```

**Request — Sora-2 12 seconds (Text-to-Video) / Sora-2 12 秒 文字转视频:**
```json
{
  "model": "Sora-2-12",
  "size": "1280x720",
  "messages": [
    {"role": "user", "content": "a small bird flying over a green meadow"}
  ]
}
```

**Request — Sora-2 16 seconds (Text-to-Video) / Sora-2 16 秒 文字转视频:**
```json
{
  "model": "Sora-2-16",
  "size": "1280x720",
  "messages": [
    {"role": "user", "content": "a small bird flying over a green meadow"}
  ]
}
```

**Request — Sora-2 (Image-to-Video, optional reference) / Sora-2 图片转视频 (可选参考图):**
```json
{
  "model": "Sora-2-12",
  "size": "1280x720",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example.com/scene.jpg"}},
      {"type": "text", "text": "Animate this scene with gentle camera motion"}
    ]}
  ]
}
```

> **Sora-2 注意事项 / Notes:**
> - Model name **case-sensitive**:`Sora-2-12` / `Sora-2-16`(严格大小写)
> - `size` is **required** in the request body. Only `1280x720` (landscape) and `720x1280` (portrait) are accepted; other values return 400.  
>   `size` 字段必填，只支持 `1280x720`（横屏）或 `720x1280`（竖屏），其他值会返回 400。
> - Reference image is optional (max 1 image). With image → image-to-video; without → text-to-video.  
>   参考图可选（最多 1 张），有图为图生视频，无图为文生视频。
> - Generation typically takes 2–5 minutes per video.  
>   单条视频生成通常需 2–5 分钟。

> **Tier Choice Guide / 档位选择建议：**
> - **Lite / 轻量**: lowest cost, may take longer to start — ideal for previews and batch jobs / 最低价，启动时间可能略长，适合预览和批量任务
> - **Fast / 快速**: balanced speed and quality, default for most use cases / 速度与质量平衡，多数场景默认
> - **Quality / 高质量**: highest fidelity, longest wait / 最高画质，耗时最长

Both formats are supported for R2I/I2V/R2V images:
R2I/I2V/R2V 图片支持两种格式：
- **URL**: `"url": "https://example.com/image.jpg"` — auto downloaded / 自动下载转换
- **Base64**: `"url": "data:image/jpeg;base64,/9j/4AAQ..."` — sent directly / 直接发送

Supported image formats / 支持格式: JPEG, PNG, WebP

**Response / 响应 (202 Accepted):**
```json
{
  "task_id": "abc123def456",
  "status": "queued",
  "position": 12,
  "cost": 12,
  "model": "gemini-3.0-pro-image-landscape",
  "created_at": "2026-03-26T12:00:00+00:00"
}
```

| Field / 字段 | Description / 说明 |
|---|---|
| `task_id` | Unique task identifier / 任务唯一标识 |
| `status` | `queued` = waiting in queue / 排队中 |
| `position` | Queue position / 队列位置 |
| `cost` | Credits deducted / 扣除积分数 |

**Error Responses / 错误响应:**
| Status / 状态码 | Meaning / 含义 |
|--------|---------|
| 401 | Missing or invalid API key / API Key 缺失或无效 |
| 400 | Invalid model, bad JSON, or image download failed / 无效模型、JSON格式错误或图片下载失败 |
| 402 | Insufficient credits / 积分不足 |
| 429 | Rate limit or daily limit exceeded / 频率限制或每日限额已达 |
| 503 | All generators busy or service paused / 所有生成器繁忙或服务暂停 |

---

### 2. Query Task Status / 查询任务状态

`GET /v1/tasks/{task_id}`

Poll this endpoint to track task progress. Recommended interval: 5-10 seconds.
轮询此接口获取任务进度，建议间隔 5-10 秒。

**Response — Queued / 排队中:**
```json
{
  "task_id": "abc123",
  "status": "queued",
  "position": 8,
  "model": "gemini-3.0-pro-image-landscape",
  "cost": 12,
  "created_at": "2026-03-26 12:00:00"
}
```

**Response — Processing / 处理中:**
```json
{
  "task_id": "abc123",
  "status": "processing",
  "model": "gemini-3.0-pro-image-landscape",
  "cost": 12,
  "created_at": "2026-03-26 12:00:00",
  "started_at": "2026-03-26 12:00:30"
}
```

**Response — Completed / 已完成:**
```json
{
  "task_id": "abc123",
  "status": "completed",
  "model": "gemini-3.0-pro-image-landscape",
  "task_type": "t2i",
  "cost": 12,
  "created_at": "2026-03-26 12:00:00",
  "completed_at": "2026-03-26 12:01:05",
  "expires_at": "2026-03-28 12:01:05",
  "result": {
    "file_url": "/v1/tasks/abc123/file",
    "file_ext": "png",
    "file_size": 1234567,
    "duration_ms": 45000,
    "type": "t2i"
  }
}
```

| Field / 字段 | Description / 说明 |
|---|---|
| `file_url` | File download path / 文件下载路径 |
| `file_ext` | File extension: png, jpg, mp4 / 文件扩展名 |
| `file_size` | File size in bytes / 文件大小（字节） |
| `duration_ms` | Generation time in ms / 生成耗时（毫秒） |
| `type` | Task type: t2i, r2i, t2v, i2v, r2v / 任务类型 |
| `expires_at` | File expiry time (48h retention) / 文件过期时间（保留48小时） |

**Response — Failed / 失败:**
```json
{
  "task_id": "abc123",
  "status": "failed",
  "error": "Content policy violation",
  "refunded": true
}
```

All failed tasks are automatically refunded. / 所有失败任务自动退还积分。

**Response — Cancelled / 已取消:**
```json
{
  "task_id": "abc123",
  "status": "cancelled",
  "refunded": true
}
```

---

### 3. Download Result File / 下载结果文件

`GET /v1/tasks/{task_id}/file`

Download the generated image or video file. Only available for `completed` tasks.
下载生成的图片或视频文件，仅对已完成的任务有效。

**Response:** Binary file with appropriate `Content-Type` header.
- Images / 图片: `image/png`, `image/jpeg`, `image/webp`
- Videos / 视频: `video/mp4`

Files are retained for **48 hours** after completion.
文件在完成后保留 **48 小时**。

---

### 4. List Tasks / 任务列表

`GET /v1/tasks`

List your generation tasks with optional filtering.
查询自己的生成任务列表，支持过滤和分页。

**Query Parameters / 查询参数:**
| Param / 参数 | Type / 类型 | Description / 说明 |
|-------|------|-------------|
| `status` | string | Filter / 过滤: `queued`, `processing`, `completed`, `failed`, `cancelled` |
| `limit` | int | Max results, default 50, max 200 / 最大结果数 |
| `offset` | int | Pagination offset / 分页偏移 |

**Response / 响应:**
```json
{
  "tasks": [
    {
      "task_id": "abc",
      "model": "gemini-3.0-pro-image-landscape",
      "task_type": "t2i",
      "status": "completed",
      "cost": 12,
      "created_at": "2026-03-26 12:00:00",
      "completed_at": "2026-03-26 12:01:05"
    }
  ],
  "total": 150,
  "queued": 3,
  "processing": 1,
  "completed": 140,
  "failed": 6
}
```

---

### 5. Cancel Task / 取消任务

`DELETE /v1/tasks/{task_id}`

Cancel a queued task. Credits are refunded immediately. Only `queued` tasks can be cancelled.
取消排队中的任务，积分立即退还。仅 queued 状态可取消。

**Response / 响应:**
```json
{
  "ok": true,
  "task_id": "abc123",
  "refunded": 12
}
```

---

### 6. Account Info / 账户信息

`GET /me`

Get your current key's balance and usage stats.
查询当前 key 的余额和使用量。

**Response / 响应:**
```json
{
  "id": 8,
  "name": "MyKey",
  "credits": 29800.0,
  "frozen_credits": 0.0,
  "img_30d": 150,
  "vid_30d": 45,
  "today_img": 12,
  "today_vid": 3,
  "daily_used": 15,
  "daily_credits_used": 180.0,
  "daily_limit": 0,
  "rpm_limit": 0,
  "account_id": 7,
  "key_label": "prod-1",
  "account_name": "MyCompany",
  "tier_thresholds": [...],
  "effective_pricing": { "...": "see /me response for your personal pricing" }
}
```

| Field / 字段 | Description / 说明 |
|---|---|
| `credits` | Current key balance / 当前 key 余额 |
| `frozen_credits` | Credits reserved for in-progress tasks / 进行中任务冻结的积分 |
| `img_30d` / `vid_30d` | 30-day rolling count (affects pricing tier) / 30天滚动量（影响定价等级） |
| `today_img` / `today_vid` | Today's generation count / 今日生成量 |
| `daily_used` | Today's total requests / 今日总请求数 |
| `daily_credits_used` | Today's total credits consumed / 今日消耗积分 |
| `daily_limit` | Daily request limit (0 = unlimited) / 每日请求限制（0=无限） |
| `rpm_limit` | Requests per minute limit (0 = unlimited) / 每分钟请求限制（0=无限） |
| `tier_thresholds` | Volume tier boundaries / 阶梯用量分界线 |
| `effective_pricing` | Your personalized per-model pricing / 您的专属每模型定价 |

> Per-model pricing is returned by `GET /me` in the `effective_pricing` field. Refer to that response for your account's current pricing.
>
> 各模型实时定价由 `GET /me` 接口的 `effective_pricing` 字段返回，请以该响应为准。

---

### 7. Account Management / 账户管理（多 Key）

> These endpoints require **account password login** via the Dashboard. API key login only provides single-key view.
>
> 这些接口需要通过 Dashboard **使用账户密码登录**。API key 登录只能查看单个 key。

**Account Overview / 账户概览:** `GET /me/account`

```json
{
  "account": {
    "id": 7,
    "name": "MyCompany",
    "credit_pool": 0.0
  },
  "total_credits": 50000.0,
  "keys": [
    {"id": 10, "name": "prod-1", "key_label": "production", "credits": 30000, "is_active": true},
    {"id": 11, "name": "prod-2", "key_label": "staging", "credits": 20000, "is_active": true}
  ]
}
```

**Create Key / 创建 Key:** `POST /me/account/keys`
```json
{"name": "new-key", "label": "testing"}
```

**Delete Key / 删除 Key:** `DELETE /me/account/keys/{key_id}`

**Allocate Credits / 分配积分:** `POST /me/account/allocate`
```json
{"from_key_id": 10, "to_key_id": 11, "amount": 5000}
```

**Change Password / 修改密码:** `POST /me/account/password`
```json
{"old_password": "...", "new_password": "..."}
```

**Account Stats / 账户统计:** `GET /me/account/stats`

---

### 8. Usage History / 使用记录

`GET /me/usage`

Query usage history with optional date filter.
查询使用记录，可按日期过滤。

| Param / 参数 | Type / 类型 | Description / 说明 |
|-------|------|-------------|
| `date` | string | Filter by date / 按日期过滤: `YYYY-MM-DD` |

---

### 9. Credit History / 积分交易记录

`GET /me/transactions`

| Param / 参数 | Type / 类型 | Description / 说明 |
|-------|------|-------------|
| `limit` | int | Max results, default 50, max 500 / 最大结果数 |
| `offset` | int | Pagination offset / 分页偏移 |
| `date` | string | Filter by date / 按日期: `YYYY-MM-DD` |
| `type` | string | Filter / 过滤: `charge`(消费), `refund`(退款), `topup`(充值), `adjust`(调整) |
| `task_type` | string | Filter / 过滤: `t2i`, `r2i`, `t2v`, `i2v`, `r2v` |

---

### 10. List Models / 模型列表

`GET /v1/models`

Returns all available models.
返回所有可用模型。

---

### 11. Service Health / 服务状态

`GET /health` *(no auth required / 无需认证)*

Check if the service is online before submitting tasks.
提交任务前检查服务是否在线。

```json
{
  "service": "holo-gen-reception",
  "status": "ok",
  "capacity": "available"
}
```

| Field / 字段 | Description / 说明 |
|---|---|
| `status` | `ok` = online / 在线 |
| `capacity` | `available` = accepting tasks / 可接受任务, `busy` = high load / 高负载 |

---

### 12. Announcements / 公告

`GET /banner` *(no auth required / 无需认证)*

Get active announcements.
获取当前有效公告。

```json
{
  "text": "System maintenance at 03:00 UTC",
  "visible": true,
  "banners": []
}
```

| Field / 字段 | Description / 说明 |
|---|---|
| `text` | Current announcement text (empty if none) / 当前公告文字（无公告时为空） |
| `visible` | Whether announcement is active / 公告是否生效 |
| `banners` | List of all active banners / 所有生效公告列表 |

---

## Available Models / 可用模型

### Image Generation / 图片生成 (Text-to-Image / 文字生图)

| Model / 模型 | Resolution / 分辨率 |
|-------|-----------|
| `gemini-3.0-pro-image-{orientation}` | Standard / 标准 |
| `gemini-3.0-pro-image-{orientation}-2k` | 2K |
| `gemini-3.0-pro-image-{orientation}-4k` | 4K |
| `gemini-3.1-flash-image-{orientation}` | Standard / 标准 |
| `gemini-3.1-flash-image-{orientation}-2k` | 2K |
| `gemini-3.1-flash-image-{orientation}-4k` | 4K |
| `imagen-4.0-generate-preview-{orientation}` | Standard / 标准 |

**Gemini orientations / Gemini 方向:** `landscape`, `portrait`, `square`, `four-three`, `three-four`

**Imagen orientations / Imagen 方向:** `landscape`, `portrait`

### Image Generation / 图片生成 (Reference-to-Image / 参考生图 R2I)

> R2I uses the same image model names as Text-to-Image. When the request contains `image_url`, it is automatically detected as R2I and billed at R2I pricing.
>
> R2I 使用与文字生图完全相同的模型名。当请求中包含 `image_url` 时，自动识别为 R2I 并按 R2I 价格计费。

| Model / 模型 | Resolution / 分辨率 |
|-------|-----------|
| `gemini-3.0-pro-image-{orientation}` + image_url | Standard / 标准 |
| `gemini-3.0-pro-image-{orientation}-2k` + image_url | 2K |
| `gemini-3.0-pro-image-{orientation}-4k` + image_url | 4K |
| `gemini-3.1-flash-image-{orientation}` + image_url | Standard / 标准 |
| `gemini-3.1-flash-image-{orientation}-2k` + image_url | 2K |
| `gemini-3.1-flash-image-{orientation}-4k` + image_url | 4K |

**Orientations / 方向:** `landscape`, `portrait`, `square`, `four-three`, `three-four`

### Image Generation / 图片生成 (GPT-images2)

> OpenAI-based `gpt-image-2` series. Supports both Text-to-Image and Reference-to-Image (same model name + `image_url` auto-detects R2I). Model name contains a space — pass it verbatim.
>
> 基于 OpenAI `gpt-image-2` 系列。同时支持文生图和参考生图（带 `image_url` 自动识别为 R2I）。模型名包含空格，请原样传递。

| Model / 模型 | Output / 实际尺寸 | Notes / 说明 |
|---|---|---|
| `GPT-images2` | 1024×1024 | Default / 默认 |
| `GPT-images2 1:1` | 1024×1024 | Square 1K / 方形 1K |
| `GPT-images2 1:1-2K` | 1920×1920 | Square 2K / 方形 2K |
| `GPT-images2 3:2-2K` | 1920×1280 | Landscape 3:2 / 横版 3:2 |
| `GPT-images2 2:3-2K` | 1280×1920 | Portrait 2:3 / 竖版 2:3 |
| `GPT-images2 16:9-2K` | 1920×1088 | Widescreen 2K / 宽屏 2K |
| `GPT-images2 16:9-4K` | 3840×2160 | Widescreen 4K / 宽屏 4K |
| `GPT-images2 9:16-4K` | 2160×3840 | Vertical 4K / 竖屏 4K |

### Video Generation / 视频生成 (Text-to-Video / 文字转视频)

**Orientations / 方向:** `landscape`, `portrait`
**Tiers / 档位:** `lite` (lowest cost, may take longer to start / 最低价，启动时间可能略长)、`fast` (balanced speed and quality / 速度与质量平衡)、`quality` (highest fidelity / 最高画质)

#### 8 seconds (default) / 8 秒（默认）— supports 1080p / 4K

| Model / 模型 | Tier / 档位 | Resolution / 分辨率 |
|-------|------|-----------|
| `veo_3_1_t2v_lite_{orientation}` | Lite | 720p |
| `veo_3_1_t2v_fast_{orientation}` | Fast | 720p |
| `veo_3_1_t2v_fast_{orientation}_1080p` | Fast | 1080p |
| `veo_3_1_t2v_fast_{orientation}_4k` | Fast | 4K |
| `veo_3_1_t2v_{orientation}` | Quality | 720p |
| `veo_3_1_t2v_{orientation}_1080p` | Quality | 1080p |
| `veo_3_1_t2v_{orientation}_4k` | Quality | 4K |

#### 4 seconds / 4 秒 — 720p only

| Model / 模型 | Tier / 档位 | Resolution / 分辨率 |
|-------|------|-----------|
| `veo_3_1_t2v_lite_4s_{orientation}` | Lite | 720p |
| `veo_3_1_t2v_fast_4s_{orientation}` | Fast | 720p |
| `veo_3_1_t2v_quality_4s_{orientation}` | Quality | 720p |

#### 6 seconds / 6 秒 — 720p only

| Model / 模型 | Tier / 档位 | Resolution / 分辨率 |
|-------|------|-----------|
| `veo_3_1_t2v_lite_6s_{orientation}` | Lite | 720p |
| `veo_3_1_t2v_fast_6s_{orientation}` | Fast | 720p |
| `veo_3_1_t2v_quality_6s_{orientation}` | Quality | 720p |

---

### Video Generation / 视频生成 (Image-to-Video / 图片转视频)

#### 8 seconds (default) / 8 秒（默认）— supports 1080p / 4K

| Model / 模型 | Tier / 档位 | Resolution / 分辨率 |
|-------|------|-----------|
| `veo_3_1_i2v_lite_{orientation}` | Lite | 720p |
| `veo_3_1_i2v_fast_{orientation}` | Fast | 720p |
| `veo_3_1_i2v_fast_{orientation}_1080p` | Fast | 1080p |
| `veo_3_1_i2v_fast_{orientation}_4k` | Fast | 4K |
| `veo_3_1_i2v_s_{orientation}` | Quality | 720p |
| `veo_3_1_i2v_s_{orientation}_1080p` | Quality | 1080p |
| `veo_3_1_i2v_s_{orientation}_4k` | Quality | 4K |

#### 4 seconds / 4 秒 — 720p only

| Model / 模型 | Tier / 档位 | Resolution / 分辨率 |
|-------|------|-----------|
| `veo_3_1_i2v_lite_4s_{orientation}` | Lite | 720p |
| `veo_3_1_i2v_fast_4s_{orientation}` | Fast | 720p |
| `veo_3_1_i2v_quality_4s_{orientation}` | Quality | 720p |

#### 6 seconds / 6 秒 — 720p only

| Model / 模型 | Tier / 档位 | Resolution / 分辨率 |
|-------|------|-----------|
| `veo_3_1_i2v_lite_6s_{orientation}` | Lite | 720p |
| `veo_3_1_i2v_fast_6s_{orientation}` | Fast | 720p |
| `veo_3_1_i2v_quality_6s_{orientation}` | Quality | 720p |

---

### Video Generation / 视频生成 (Reference-to-Video / 参考转视频)

> **Note:** R2V supports only 8s duration. R2V Quality tier is not available.
> **注意：** R2V 仅支持 8 秒时长。R2V 不提供 Quality 档。

| Model / 模型 | Tier / 档位 | Resolution / 分辨率 |
|-------|------|-----------|
| `veo_3_1_r2v_lite_{orientation}` | Lite | 720p |
| `veo_3_1_r2v_fast_{orientation}` | Fast | 720p |
| `veo_3_1_r2v_fast_{orientation}_1080p` | Fast | 1080p |
| `veo_3_1_r2v_fast_{orientation}_4k` | Fast | 4K |

---

### Video Generation / 视频生成 (Sora-2)

> OpenAI Sora-2 model. **`size` is required in request body.** Reference image is optional (max 1, via `image_url` in messages); without image is text-to-video, with image is image-to-video.
>
> OpenAI Sora-2 模型。**`size` 字段必填**。参考图可选（最多 1 张，messages 里的 `image_url`），无图为文生视频，有图为图生视频。

| Model / 模型 | Duration / 时长 | Sizes / 支持尺寸 |
|---|---|---|
| `Sora-2-12` | 12 seconds / 12 秒 | `1280x720`, `720x1280` |
| `Sora-2-16` | 16 seconds / 16 秒 | `1280x720`, `720x1280` |

**Note / 注意:** Model name is **case-sensitive**(严格大小写,首字母大写 S)。Generation typically takes 2–5 minutes / 单条视频生成通常需 2–5 分钟。

---

## Content Safety / 内容安全

Requests that violate Google's content policies are automatically rejected and **refunded in full**.
违反 Google 内容政策的请求会被自动拒绝，积分**全额退还**。

Common rejection reasons / 常见拒绝原因:

| Code / 错误码 | Meaning / 含义 |
|------|---------|
| `PUBLIC_ERROR_PROMINENT_PEOPLE_UPLOAD` | Input image contains a public figure / 输入图含名人 |
| `PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED` | Output resembles a public figure / 输出类似名人 |
| `PUBLIC_ERROR_SEXUAL` | Sexual or explicit content / 色情内容 |
| `PUBLIC_ERROR_VIOLENCE` | Violence or dangerous activities / 暴力内容 |
| `PUBLIC_ERROR_DANGEROUS` | Dangerous content / 危险内容 |

---

## Error Handling / 错误处理

### Submission Errors / 提交错误（立即返回）

| Status / 状态码 | Meaning / 含义 | Action / 建议 |
|--------|---------|--------|
| 202 | Task accepted / 任务已接受 | Poll `/v1/tasks/{id}` / 轮询获取结果 |
| 400 | Invalid request / 请求无效 | Fix parameters / 检查参数 |
| 401 | Missing or invalid API key / API Key 无效 | Check your key / 检查 API Key |
| 402 | Insufficient credits / 积分不足 | Top up / 充值 |
| 429 | Rate limit exceeded / 频率限制 | Wait and retry / 等待后重试 |
| 503 | Service unavailable / 服务不可用 | Retry later / 稍后重试 |

### Task Failure / 任务失败（通过轮询获取）

All failed tasks are **automatically refunded** (`"refunded": true`).
所有失败任务**自动退还积分**。

---

## Quick Start / 快速上手

### Image Generation / 图片生成

```python
import requests
import time

API_KEY = "your_api_key_here"  # 替换为你的 API Key
BASE = "https://api.dealonhorizon.us"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 1. Submit / 提交
resp = requests.post(f"{BASE}/v1/generate", headers=HEADERS, json={
    "model": "gemini-3.0-pro-image-landscape",
    "messages": [{"role": "user", "content": "A sunset over mountains"}]
})
task = resp.json()
print(f"Task {task['task_id']} queued at position {task['position']}")

# 2. Poll / 轮询
while True:
    status = requests.get(f"{BASE}/v1/tasks/{task['task_id']}", headers=HEADERS).json()
    if status["status"] == "completed":
        # 3. Download / 下载
        file_resp = requests.get(f"{BASE}{status['result']['file_url']}", headers=HEADERS)
        ext = status["result"].get("file_ext", "png")
        with open(f"result.{ext}", "wb") as f:
            f.write(file_resp.content)
        print(f"Saved! ({status['result']['file_size']} bytes)")
        break
    elif status["status"] == "failed":
        print(f"Failed: {status.get('error')} (refunded: {status.get('refunded')})")
        break
    time.sleep(5)
```

### Video Generation / 视频生成

```python
# Text-to-Video / 文字转视频
resp = requests.post(f"{BASE}/v1/generate", headers=HEADERS, json={
    "model": "veo_3_1_t2v_fast_landscape",
    "messages": [{"role": "user", "content": "A drone shot flying over a tropical island"}]
})
# Poll same as image / 轮询方式和图片完全一样

# Image-to-Video / 图片转视频
resp = requests.post(f"{BASE}/v1/generate", headers=HEADERS, json={
    "model": "veo_3_1_i2v_fast_landscape",
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}},
        {"type": "text", "text": "Slowly zoom in with gentle camera movement"}
    ]}]
})
# Poll same as image / 轮询方式和图片完全一样
```

### Batch Processing / 批量处理

```python
# For batch generation, submit multiple /v1/generate requests
# 批量生成时，提交多个 /v1/generate 请求

import concurrent.futures

prompts = [f"Beautiful landscape scene #{i}" for i in range(50)]
tasks = []

# Submit all tasks / 提交所有任务
for prompt in prompts:
    resp = requests.post(f"{BASE}/v1/generate", headers=HEADERS, json={
        "model": "gemini-3.0-pro-image-landscape",
        "messages": [{"role": "user", "content": prompt}]
    })
    tasks.append(resp.json()["task_id"])
    time.sleep(0.5)  # Respect rate limits / 注意频率限制

# Poll all tasks / 轮询所有任务
for task_id in tasks:
    while True:
        st = requests.get(f"{BASE}/v1/tasks/{task_id}", headers=HEADERS).json()
        if st["status"] in ("completed", "failed"):
            if st["status"] == "completed":
                # Download file / 下载文件
                file_resp = requests.get(f"{BASE}{st['result']['file_url']}", headers=HEADERS)
                with open(f"{task_id[:8]}.{st['result']['file_ext']}", "wb") as f:
                    f.write(file_resp.content)
            break
        time.sleep(3)
```

---

## Limits / 使用限制

- **Queue Timeout / 排队超时**: If the system is busy, your task may wait in queue. If it cannot start in time, it will be cancelled and credits refunded automatically. / 系统繁忙时任务会排队，超时未处理将自动取消并退款。
- **File Retention / 文件保留**: 48 hours after generation / 生成后保留 48 小时
- **Fair Queuing / 公平排队**: All users share equal priority / 所有用户享有平等优先级

---

## Dashboard / 控制面板

Web dashboard / 网页控制面板: `https://api.dealonhorizon.us/dashboard`

- **API Key login** / API Key 登录: View your balance, usage history, and transaction records / 查看余额、使用记录、交易记录
- **Account password login** / 账户密码登录: Full account management — all keys, allocate credits, create/delete keys / 完整账户管理
- Light/dark theme, Chinese/English / 明暗主题、中英文切换
