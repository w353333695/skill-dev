# 两源差异报告

| 模型 | 上报 | 管理 | 合并 | 双源一致 | 双源差异 | 仅上报 | 仅管理 | 孤儿 |
|---|---|---|---|---|---|---|---|---|
| onlineBehavior@FINTECHDATA | 13 | 13 | 13 | 13 | 0 | 0 | 0 | 0 |
| uninterrupted@FINTECHDATA | 44 | 44 | 44 | 44 | 0 | 0 | 0 | 0 |
| centralAirCondition@FINTECHDATA | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0 |
| switches@FINTECHDATA | 407 | 407 | 407 | 407 | 0 | 0 | 0 | 0 |
| lowVoltage@FINTECHDATA | 2 | 2 | 4 | 0 | 0 | 2 | 2 | 0 |
| powerSupplyRelation@FINTECHDATA | 630 | 630 | 630 | 629 | 1 | 0 | 0 | 0 |
| fiberSwitch@FINTECHDATA | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| idsIps@FINTECHDATA | 19 | 19 | 19 | 19 | 0 | 0 | 0 | 0 |
| humidification@FINTECHDATA | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| environmentalMonitoring@FINTECHDATA | 18 | 18 | 18 | 18 | 0 | 0 | 0 | 0 |
| generator@FINTECHDATA | 19 | 19 | 19 | 19 | 0 | 0 | 0 | 0 |
| transformer@FINTECHDATA | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0 |
| basedSoftware@FINTECHDATA | 95 | 95 | 95 | 95 | 0 | 0 | 0 | 0 |
| application@FINTECHDATA | 43 | 43 | 43 | 43 | 0 | 0 | 0 | 0 |
| applicationRelation@FINTECHDATA | 44 | 44 | 44 | 44 | 0 | 0 | 0 | 0 |
| applicationSoftRelation@FINTECHDATA | 43 | 43 | 43 | 43 | 0 | 0 | 0 | 0 |
| dataCenter@FINTECHDATA | 19 | 0 | 19 | 0 | 0 | 19 | 0 | 0 |
| dataCenterSpacing@FINTECHDATA | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| freshAir@FINTECHDATA | 21 | 21 | 21 | 21 | 0 | 0 | 0 | 0 |
| commonAirCondition@FINTECHDATA | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| rackServer@FINTECHDATA | 157 | 157 | 157 | 157 | 0 | 0 | 0 | 0 |
| commonCabinet@FINTECHDATA | 459 | 450 | 459 | 450 | 0 | 9 | 0 | 0 |
| wdm@FINTECHDATA | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0 |
| fireProtection@FINTECHDATA | 49 | 49 | 49 | 49 | 0 | 0 | 0 | 0 |
| precisionAirCondition@FINTECHDATA | 43 | 43 | 43 | 43 | 0 | 0 | 0 | 0 |
| precisionPower@FINTECHDATA | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| networkLine@FINTECHDATA | 269 | 269 | 269 | 269 | 0 | 0 | 0 | 0 |
| networkRelation@FINTECHDATA | 496 | 496 | 496 | 496 | 0 | 0 | 0 | 0 |
| virtualMachine@FINTECHDATA | 197 | 197 | 197 | 197 | 0 | 0 | 0 | 0 |
| videoMonitoring@FINTECHDATA | 19 | 19 | 19 | 19 | 0 | 0 | 0 | 0 |
| router@FINTECHDATA | 41 | 41 | 41 | 41 | 0 | 0 | 0 | 0 |
| softwareRelation@FINTECHDATA | 90 | 90 | 90 | 90 | 0 | 0 | 0 | 0 |
| opsAudit@FINTECHDATA | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0 |
| entranceGuard@FINTECHDATA | 20 | 20 | 20 | 20 | 0 | 0 | 0 | 0 |
| firewall@FINTECHDATA | 36 | 35 | 36 | 35 | 0 | 1 | 0 | 0 |
| highVoltage@FINTECHDATA | 3 | 3 | 3 | 3 | 0 | 0 | 0 | 0 |

- **ab9197d730ea4573a34e9b48d3c87d39** (powerSupplyRelation@FINTECHDATA)
  - powerUsedAsset: 上报=平顶山市中支中心机房 | 管理=cef9b1d212644d818ae42965f7395b25
- **a76bf329024546fdad0210d032febb82** (dataCenterSpacing@FINTECHDATA)
  - localDb: 上报=郑州中支主中心机房 | 管理=77e1d9d6869044889909f41f30517418
  - oppositeDb: 上报=郑州中支转接中心机房 | 管理=96f680d2b4f348a198a690325356a7c4