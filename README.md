# KVCache C++ Packer

这个项目提供了一个自动化的构建系统，用于编译和打包 KVCache 项目所需的所有 C++ 依赖库。

## 📦 包含的库

- **etcd-cpp-apiv3** - etcd C++ API 客户端
- **gflags** - Google 命令行标志库
- **glog** - Google 日志库
- **jsoncpp** - JSON 解析库
- **rdma-core** - RDMA 核心库
- **yalantinglibs** - 高性能 C++ 库集合

## 🏗️ 构建方式

### 本地构建

```bash
# 直接构建（需要 Ubuntu 20.04 环境）
python3 pack.py

# 使用容器构建（推荐）
python3 pack_in_container.py
```

### GitHub Actions 自动构建

#### 1. 测试构建

使用 `test-build.yml` workflow 进行手动测试：

1. 访问 GitHub repository 的 Actions 页面
2. 选择 "Test Build" workflow
3. 点击 "Run workflow"
4. 选择目标架构（amd64 或 arm64）
5. 点击 "Run workflow" 按钮

#### 2. 发布版本

使用 `build-and-release.yml` workflow 自动构建和发布：

1. 创建版本标签：
```bash
git tag v1.0.0
git push origin v1.0.0
```

2. GitHub Actions 将自动：
   - 为 amd64 和 arm64 架构构建包
   - 创建 `pack_amd64.tar.gz` 和 `pack_arm64.tar.gz`
   - 生成 SHA256 校验和
   - 创建 GitHub Release 并上传文件

## 📋 输出结果

构建完成后，输出目录包含：

- `pack_{arch}.tar.gz` - 编译好的库文件包
- `pack_{arch}.tar.gz.sha256` - SHA256 校验和
- `build_summary.txt` - 构建摘要
- `build_report.json` - 详细构建报告

## 🚀 使用方法

1. 下载对应架构的包：
```bash
# 下载并验证
wget https://github.com/your-repo/releases/download/v1.0.0/pack_amd64.tar.gz
wget https://github.com/your-repo/releases/download/v1.0.0/pack_amd64.tar.gz.sha256
sha256sum -c pack_amd64.tar.gz.sha256
```

2. 解压并使用：
```bash
# 解压到指定目录
mkdir -p /opt/kvcache-deps
tar -xzf pack_amd64.tar.gz -C /opt/kvcache-deps
```

3. 在 CMake 项目中使用：
```cmake
# 设置依赖路径
set(CMAKE_PREFIX_PATH "/opt/kvcache-deps" ${CMAKE_PREFIX_PATH})

# 查找并链接库
find_package(gflags REQUIRED)
find_package(glog REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(JSONCPP jsoncpp)

target_link_libraries(your_target
    gflags::gflags
    glog::glog
    ${JSONCPP_LIBRARIES}
)
```

## 🔧 配置说明

### 包配置

所有包的配置都在 `pack.py` 中的 `PACKS` 字典中定义：

```python
PACKS = {
    "https://github.com/AI-Infra-Team/glog": {
        "branch": "v0.6.0",
        "c++": 17,
        "dependencies": ["gflags"],
        "build_type": "Release",
        "define": [
            ["WITH_GFLAGS", "ON"],
            ["BUILD_SHARED_LIBS", "OFF"],
        ],
    },
    # ... 其他包配置
}
```

### APT 依赖

系统依赖包列表在 `pack.py` 中的 `APT` 数组中定义。

## 🐳 Docker 支持

`pack_in_container.py` 脚本会：

1. 创建基于 Ubuntu 20.04 的 Docker 镜像
2. 安装所有必需的 APT 包
3. 在容器中执行构建
4. 将结果挂载到主机目录

## 📊 构建状态

- ✅ **AMD64**: 完全支持
- ✅ **ARM64**: 通过 QEMU 模拟支持

## 🏗️ GitHub Actions 环境

- **Runner**: Ubuntu 22.04 (GitHub Actions)
- **Container**: Ubuntu 20.04 (Docker)
- **多架构支持**: 通过 Docker Buildx 和 QEMU 模拟

> 注意：GitHub Actions runner 使用 Ubuntu 22.04，但构建容器仍使用 Ubuntu 20.04 以确保兼容性。Docker 会自动拉取对应架构的 ubuntu:20.04 镜像。

## 🤝 贡献

1. Fork 这个项目
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -am 'Add some feature'`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 LICENSE 文件了解详情。

## 🔗 相关链接

- [etcd-cpp-apiv3](https://github.com/AI-Infra-Team/etcd-cpp-apiv3)
- [gflags](https://github.com/AI-Infra-Team/gflags)
- [glog](https://github.com/AI-Infra-Team/glog)
- [jsoncpp](https://github.com/AI-Infra-Team/jsoncpp)
- [rdma-core](https://github.com/AI-Infra-Team/rdma-core)
- [yalantinglibs](https://github.com/AI-Infra-Team/yalantinglibs) 