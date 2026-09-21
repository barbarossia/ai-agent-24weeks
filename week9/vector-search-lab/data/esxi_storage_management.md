# ESXi 存储与虚拟磁盘维护手册

## 存储架构与数据存储类型

VMware ESXi 虚拟化主机的存储子系统负责为虚拟机（VM）提供持久化磁盘空间。
常见的数据存储（Datastore）类型：
1. **VMFS（Virtual Machine File System）**：高性能集群文件系统，直接构建在本地 NVMe/SATA SSD 或 RAID 卡呈现的块设备上。
2. **NFS 数据存储**：挂载自 HomeLab NAS（如 TrueNAS / Synology）的共享目录，常用于存放 ISO 镜像、虚拟机冷备份或共享模板。
3. **vSAN**：分布式软件定义存储，在单机 HomeLab 环境中通常使用单块高速 NVMe 建立独立 VMFS 数据存储。

## 磁盘空间不足告警排查

虚拟机运行过程中，若数据存储剩余可用容量低于阈值（如 10%），vCenter 或 ESXi 会触发警告甚至暂停虚拟机执行。

主要诱因与应对策略：
- **快照堆积（Snapshot Ballooning）**：虚拟机创建快照后，基盘变为只读，增量数据写入 delta 磁盘。若快照长期未删除，delta 文件会迅速膨胀直至耗尽卷空间。
  - 处理动作：在 vSphere Client 中执行「全部删除快照」（Consolidate Snapshots），合并增量数据到基盘。
- **精简置备（Thin Provisioning）超分配**：多个精简置备磁盘的名义容量总和超过物理磁盘容量。一旦实际写入突增，会引发空间耗尽。
  - 监控命令：通过 SSH 登录执行 `esxcli storage filesystem list` 检查真实占用与可用百分比。

## 维护最佳实践

1. 严禁将测试虚拟机快照保留超过 72 小时。
2. 保持数据存储至少 20% 的可用缓冲空间，供虚拟机交换文件（.vswp）与内存镜像使用。
3. 定期使用 `esxcli storage core device list` 查看物理磁盘 S.M.A.R.T. 状态与介质磨损寿命。
