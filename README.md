# 06-pricecab（价签柜）

Pricecab — 改价单按预约时刻生效，现行价签可查，并与销售夹具对账。

与 Feedstitch（多源归并）、Batchgate（作业编排）、Syncledger（双端对账）、Changecast（CDC 投影）、Proofpack（采样放行）主链路不同。  
不是电商订单/购物车，不是仓库进出库 CRUD，不是考勤 OA。夹具全本地。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5600 |
| API | http://localhost:10600 |

## 主链（0-1）

选商品建改价单（写明生效时刻）→ 拨业务钟或点「应用到期」→ 现行价签更新 → 配置成交时点窗后跑销售对账 → 窗外行按策略硬排除/标窗外，窗内不一致立旗标 → 未处置旗标在应用入口拦下该商品的到期改价（可切换为只记账）

## 对账窗与互斥策略

- **成交时点窗**：支持绝对时刻或相对业务钟（±小时），每次对账把窗配置、业务钟与解析后的绝对窗一起落库，可核。
- **窗外行（互斥）**：`exclude` 硬排除（不进明细终态，只记排除数）/ `flag` 入明细标窗外（不计不一致、不触发拦改价）。
- **窗内不一致（互斥）**：`block` 存在未处置不一致旗标则禁止该商品应用到期改价（整单暂缓、拒绝原因落 `apply_rejections`）/ `record` 只记账仍允许应用。
- 对账报告只写不改：改窗后历史报告分桶计数不变，新对账按新窗重算。
- 互证：报告排除数/窗内一致/不一致、旗标、拦改价拒绝原因、价签本可交叉核对（仪表盘汇总）。

## 冻结对账报告（钉扎行物化收口）

`POST /api/reports/freeze` 以当前业务钟钉扎一份全量对账报告（`FR-####`），全局只贯彻一种收口：**以钉扎时刻历史 as-of 物化钉扎行并冻结**。

- **钉扎同源**：只纳入 `sold_at <= 钉扎水位` 的成交；期望价取钉扎时刻可见的价签历史（`recorded_at <= 钉扎时刻`），冻结后补录的溯及价签不回流。头部计数与钉扎行同一批算出、同事务落库。
- **物化完成才标现行**：报告头先以 `materializing` 与全部钉扎行同事务写入，物化落账后才置 `current` 并退位旧现行（`superseded`）；失败整体回滚，不存在「行写一半、头已标成功」。
- **打开只读钉扎行**：`GET /api/reports/{id}` 禁止按现行价签现场重算，两次打开完全一致；响应带 `materialized`/`current` 互证标记（行数、分桶计数与头部一致才为真）。
- **拦改价读报告入口**：`block` 策略下，现行且物化互证通过的冻结报告的钉扎不一致行与未处置旗标共同拦下该商品的到期改价（拒绝原因引用报告号）；物化未完成或互证失败的报告不驱动拦改价。
- **分叉收口**：钉扎行缺失/被篡改时，`POST /api/reports/{id}/rematerialize` 按该报告自己的钉扎时刻 as-of 重建钉扎行并冻结；修复不授予现行资格。

## 验证

```bash
# 另起终端：DATA_DIR=/tmp/pricecab-data uvicorn app.main:app --port 10600（backend/ 目录下）
python3 tests/e2e_recon_window.py http://localhost:10600
python3 tests/e2e_frozen_report.py http://localhost:10600 /tmp/pricecab-data/pricecab.db
```

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。
