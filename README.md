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

## 验证

```bash
# 另起终端：DATA_DIR=/tmp/pricecab-data uvicorn app.main:app --port 10600（backend/ 目录下）
python3 tests/e2e_recon_window.py http://localhost:10600
```

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。
