#!/usr/bin/env python3
"""
KV Cache C++ Packer
自动拉取、编译、安装脚本，用于构建所有依赖包
"""

import os
import sys
import subprocess
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# 包配置
PACKS = {
    "https://github.com/AI-Infra-Team/etcd-cpp-apiv3": {
        "branch": "master",
        "c++": 17,
        "build_type": "Release",
        "define": [
            ["BUILD_STATIC_LIBS", "ON"],
            ["BUILD_SHARED_LIBS", "OFF"],
        ],
    },
    "https://github.com/AI-Infra-Team/gflags": {
        "branch": "master",
        "c++": 17,
        "build_type": "Release",
        "define": [
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
            ["BUILD_gflags_LIB", "ON"],
        ],
    },
    "https://github.com/AI-Infra-Team/glog": {
        "branch": "v0.6.0",
        "c++": 17,
        "dependencies": ["gflags"],
        "build_type": "Release",
        "define": [
            ["WITH_GFLAGS", "ON"],
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
        ],
    },
    # "https://github.com/AI-Infra-Team/googletest": {
    #     "branch": "main",
    # },
    "https://github.com/AI-Infra-Team/jsoncpp": {
        "branch": "master",
        "c++": 17,
        "define": [
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
            ["BUILD_OBJECT_LIBS", "OFF"],
            ["CMAKE_BUILD_TYPE", "Release"],
        ],
    },
    "https://github.com/AI-Infra-Team/rdma-core": {
        "branch": "master",
        "c++": 17,
        "define": [
            ["NO_PYVERBS", "ON"],
            ["BUILD_SHARED_LIBS", "ON"],
            ["BUILD_STATIC_LIBS", "OFF"],
            ["BUILD_TESTING", "OFF"],
            ["BUILD_EXAMPLES", "OFF"],
            ["BUILD_EXAMPLES", "OFF"],
            ["NO_MAN_PAGES", "ON"],
        ],
    },
    "https://github.com/AI-Infra-Team/yalantinglibs": {
        "branch": "main",
        "c++": 20,
        "dependencies": ["rdma-core"],
        "define": [
            ["GENERATE_BENCHMARK_DATA", "OFF"],
            ["BUILD_EXAMPLES", "OFF"],
            ["BUILD_BENCHMARK", "OFF"],
            ["BUILD_TESTING", "OFF"],
            ["COVERAGE_TEST", "OFF"],
        ],
    },
}
APT = [
    # 基础构建工具
    "build-essential",
    "cmake",
    "git",
    "pkg-config",
    "autoconf",
    "automake",
    "libtool",
    "wget",
    "curl",
    "python3",
    "python3-pip",
    # 开发库
    "libssl-dev",
    "zlib1g-dev",
    "ca-certificates",
    # 项目特定依赖
    "libprotobuf-dev",
    "protobuf-compiler-grpc",
    "libgrpc++-dev",
    "libgrpc-dev",
    "libunwind-dev",
    "gcc-10",
    "g++-10",
    "libcpprest-dev",
    "libnl-3-dev",
    "libnl-route-3-dev",
]
CPU_COUNT = 4  # os.cpu_count() or 4

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("build.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class Builder:
    def __init__(self, install_prefix="/output", build_dir="build", max_workers=4):
        self.install_prefix = install_prefix
        self.build_dir = Path(build_dir)
        self.build_dir.mkdir(exist_ok=True)
        self.max_workers = max_workers
        self.build_results = {}
        self.built_packages = set()  # 跟踪已构建的包

    def get_package_name(self, url: str) -> str:
        """从URL获取包名"""
        return url.split("/")[-1]

    def resolve_dependencies(self, packages: Dict) -> List[str]:
        """解析依赖关系，返回按依赖顺序排列的URL列表"""
        visited = set()
        temp_visited = set()
        result = []

        def visit(url: str):
            if url in temp_visited:
                raise ValueError(f"Circular dependency detected involving {url}")
            if url in visited:
                return

            temp_visited.add(url)

            # 处理依赖
            config = packages.get(url, {})
            dependencies = config.get("dependencies", [])

            for dep_name in dependencies:
                # 查找依赖的URL
                dep_url = None
                for pkg_url in packages:
                    if self.get_package_name(pkg_url) == dep_name:
                        dep_url = pkg_url
                        break

                if dep_url:
                    visit(dep_url)
                else:
                    logger.warning(
                        f"Dependency {dep_name} not found for {self.get_package_name(url)}"
                    )

            temp_visited.remove(url)
            visited.add(url)
            result.append(url)

        for url in packages:
            visit(url)

        return result

    def generate_cmake_args(self, config: Dict) -> str:
        """生成CMake配置参数"""
        args = []

        # 编译器设置
        if "CC" in os.environ:
            args.append(f"-DCMAKE_C_COMPILER={os.environ['CC']}")
        if "CXX" in os.environ:
            args.append(f"-DCMAKE_CXX_COMPILER={os.environ['CXX']}")

        # 基础参数
        build_type = config.get("build_type", "Release")
        args.append(f"-DCMAKE_BUILD_TYPE={build_type}")
        args.append(f"-DCMAKE_INSTALL_PREFIX={self.install_prefix}")

        # 获取C++标准
        cpp_std = config.get("c++")

        # 依赖包路径 - 使用更直接的方式
        dependencies = config.get("dependencies", [])
        if dependencies:
            # 添加PREFIX_PATH以帮助查找已安装的依赖包
            args.append(f"-DCMAKE_PREFIX_PATH={self.install_prefix}")

            # 直接在编译和链接标志中添加路径
            cxx_flags = f"-I{self.install_prefix}/include"
            linker_flags = f"-L{self.install_prefix}/lib"

            # 如果有C++标准要求，添加到CXX_FLAGS中
            if cpp_std:
                cxx_flags = f"-std=c++{cpp_std} {cxx_flags}"

            args.append(f"-DCMAKE_CXX_FLAGS='{cxx_flags}'")
            args.append(f"-DCMAKE_EXE_LINKER_FLAGS='{linker_flags}'")
            args.append(f"-DCMAKE_SHARED_LINKER_FLAGS='{linker_flags}'")

            # 为每个依赖设置特定的路径变量
            for dep_name in dependencies:
                if dep_name in self.built_packages:
                    # 设置依赖包的查找路径
                    args.append(f"-D{dep_name}_DIR={self.install_prefix}")
                    args.append(f"-D{dep_name}_ROOT={self.install_prefix}")
                    # 也尝试小写版本
                    args.append(f"-D{dep_name.lower()}_DIR={self.install_prefix}")
                    args.append(f"-D{dep_name.lower()}_ROOT={self.install_prefix}")

            # 添加pkg-config路径
            pkgconfig_path = f"{self.install_prefix}/lib/pkgconfig"
            if os.path.exists(pkgconfig_path):
                current_pkg_config = os.environ.get("PKG_CONFIG_PATH", "")
                if pkgconfig_path not in current_pkg_config:
                    if current_pkg_config:
                        os.environ["PKG_CONFIG_PATH"] = (
                            f"{current_pkg_config}:{pkgconfig_path}"
                        )
                    else:
                        os.environ["PKG_CONFIG_PATH"] = pkgconfig_path
        else:
            # 没有依赖时，正常设置C++标准
            if cpp_std:
                args.append(f"-DCMAKE_CXX_STANDARD={cpp_std}")
                args.append("-DCMAKE_CXX_STANDARD_REQUIRED=ON")

        # 自定义定义
        defines = config.get("define", [])
        for define in defines:
            if isinstance(define, list) and len(define) == 2:
                key, value = define
                args.append(f"-D{key}={value}")
            elif isinstance(define, str):
                args.append(f"-D{define}")

        # 默认关闭测试
        if not any("BUILD_TESTING" in str(define) for define in defines):
            args.append("-DBUILD_TESTING=OFF")

        return " \\\n    ".join(args)

    def run_command(self, cmd: str, cwd: str = None, check: bool = True) -> int:
        """执行shell命令"""
        logger.info(f"Running command: {cmd}")
        if cwd:
            logger.info(f"Working directory: {cwd}")
            # 切换到指定目录执行命令
            original_cwd = os.getcwd()
            os.chdir(cwd)
            try:
                result = os.system(cmd)
            finally:
                os.chdir(original_cwd)
        else:
            result = os.system(cmd)

        if check and result != 0:
            raise subprocess.CalledProcessError(result, cmd)

        return result

    def install_apt_packages(self):
        """安装APT包"""
        logger.info("Installing APT packages...")

        # 更新包列表
        self.run_command("apt-get update")

        # 直接使用APT数组中的所有包
        cmd = f"apt-get install -y {' '.join(APT)}"
        self.run_command(cmd)

        logger.info("APT packages installed successfully")

    def clone_repository(self, url: str, branch: str, target_dir: Path) -> bool:
        """克隆Git仓库"""
        try:
            if target_dir.exists():
                logger.info(
                    f"Directory {target_dir} already exists, pulling latest changes..."
                )
                self.run_command("git pull", cwd=str(target_dir))
            else:
                logger.info(f"Cloning {url} (branch: {branch}) to {target_dir}")
                self.run_command(f"git clone -b {branch} {url} {target_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to clone {url}: {e}")
            return False

    def build_cmake_project(
        self, source_dir: Path, package_name: str, config: Dict
    ) -> bool:
        """构建CMake项目"""
        try:
            build_dir = source_dir / "build"
            build_dir.mkdir(exist_ok=True)

            # 生成CMake配置参数
            cmake_args = self.generate_cmake_args(config)
            cmake_cmd = f"cmake .. \\\n    {cmake_args}"

            self.run_command(cmake_cmd, cwd=str(build_dir))

            # 编译
            self.run_command(f"make -j{CPU_COUNT}", cwd=str(build_dir))

            # 安装
            self.run_command("make install", cwd=str(build_dir))

            # 标记为已构建
            self.built_packages.add(package_name)

            logger.info(f"Successfully built and installed {package_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to build {package_name}: {e}")
            return False

    def build_autotools_project(
        self, source_dir: Path, package_name: str, config: Dict
    ) -> bool:
        """构建Autotools项目"""
        try:
            # 尝试autogen.sh或autoreconf
            if (source_dir / "autogen.sh").exists():
                self.run_command("./autogen.sh", cwd=str(source_dir))
            elif (source_dir / "configure.ac").exists() or (
                source_dir / "configure.in"
            ).exists():
                self.run_command("autoreconf -fiv", cwd=str(source_dir))

            # 配置
            configure_cmd = f"./configure --prefix={self.install_prefix}"

            # 添加编译器设置
            if "CC" in os.environ:
                configure_cmd += f" CC={os.environ['CC']}"
            if "CXX" in os.environ:
                configure_cmd += f" CXX={os.environ['CXX']}"

            # 处理依赖包路径
            dependencies = config.get("dependencies", [])
            if dependencies:
                # 添加include和lib路径到环境变量
                cppflags = f"-I{self.install_prefix}/include"
                ldflags = f"-L{self.install_prefix}/lib"

                # 检查是否已有这些环境变量
                existing_cppflags = os.environ.get("CPPFLAGS", "")
                existing_ldflags = os.environ.get("LDFLAGS", "")

                if existing_cppflags:
                    cppflags = f"{existing_cppflags} {cppflags}"
                if existing_ldflags:
                    ldflags = f"{existing_ldflags} {ldflags}"

                configure_cmd += f" CPPFLAGS='{cppflags}'"
                configure_cmd += f" LDFLAGS='{ldflags}'"

                # 设置PKG_CONFIG_PATH
                pkgconfig_path = f"{self.install_prefix}/lib/pkgconfig"
                if os.path.exists(pkgconfig_path):
                    current_pkg_config = os.environ.get("PKG_CONFIG_PATH", "")
                    if pkgconfig_path not in current_pkg_config:
                        if current_pkg_config:
                            os.environ["PKG_CONFIG_PATH"] = (
                                f"{current_pkg_config}:{pkgconfig_path}"
                            )
                        else:
                            os.environ["PKG_CONFIG_PATH"] = pkgconfig_path

            # 添加C++标准支持
            cpp_std = config.get("c++")
            if cpp_std:
                cxxflags = f"-std=c++{cpp_std}"
                if "CXXFLAGS" in configure_cmd:
                    configure_cmd = configure_cmd.replace(
                        "CXXFLAGS='", f"CXXFLAGS='{cxxflags} "
                    )
                else:
                    configure_cmd += f" CXXFLAGS='{cxxflags}'"

            self.run_command(configure_cmd, cwd=str(source_dir))

            # 编译和安装
            self.run_command(f"make -j{CPU_COUNT}", cwd=str(source_dir))
            self.run_command("make install", cwd=str(source_dir))

            # 标记为已构建
            self.built_packages.add(package_name)

            logger.info(f"Successfully built and installed {package_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to build {package_name}: {e}")
            return False

    def build_package(self, url: str, config: Dict) -> tuple:
        """构建单个包"""
        package_name = self.get_package_name(url)
        source_dir = self.build_dir / package_name
        branch = config.get("branch", "master")

        logger.info(f"Building package: {package_name}")
        logger.info(f"Configuration: {config}")

        # 克隆仓库
        if not self.clone_repository(url, branch, source_dir):
            return (package_name, False, "Failed to clone repository")

        # 刷新ldconfig
        self.run_command("ldconfig")

        # 尝试不同的构建系统
        if (source_dir / "CMakeLists.txt").exists():
            success = self.build_cmake_project(source_dir, package_name, config)
        elif (source_dir / "configure").exists() or (
            source_dir / "autogen.sh"
        ).exists():
            success = self.build_autotools_project(source_dir, package_name, config)
        else:
            logger.warning(f"Unknown build system for {package_name}, trying CMake...")
            success = self.build_cmake_project(source_dir, package_name, config)

        if success:
            return (package_name, True, "Built successfully")
        else:
            return (package_name, False, "Build failed")

    def setup_compiler_environment(self):
        """设置编译器环境变量"""
        logger.info("Setting up compiler environment...")

        # 查找gcc-10和g++-10
        gcc_10_path = None
        gxx_10_path = None

        # 常见的安装路径
        common_paths = ["/usr/bin", "/usr/local/bin", "/opt/gcc/bin"]

        for path in common_paths:
            gcc_candidate = os.path.join(path, "gcc-10")
            gxx_candidate = os.path.join(path, "g++-10")

            if os.path.exists(gcc_candidate) and os.access(gcc_candidate, os.X_OK):
                gcc_10_path = gcc_candidate
            if os.path.exists(gxx_candidate) and os.access(gxx_candidate, os.X_OK):
                gxx_10_path = gxx_candidate

            if gcc_10_path and gxx_10_path:
                break

        # 设置环境变量
        if gcc_10_path:
            os.environ["CC"] = gcc_10_path
            logger.info(f"Set CC={gcc_10_path}")
        else:
            logger.warning("gcc-10 not found, using system default")

        if gxx_10_path:
            os.environ["CXX"] = gxx_10_path
            logger.info(f"Set CXX={gxx_10_path}")
        else:
            logger.warning("g++-10 not found, using system default")

        # 验证编译器版本
        if gcc_10_path:
            logger.info("Verifying GCC version:")
            os.system(f"{gcc_10_path} --version")

        if gxx_10_path:
            logger.info("Verifying G++ version:")
            os.system(f"{gxx_10_path} --version")

    def build_all_packages(self):
        """按依赖顺序构建所有包"""
        logger.info("Starting to build all packages...")

        # 首先安装APT包
        self.install_apt_packages()

        # 设置编译器环境
        self.setup_compiler_environment()

        # 解析依赖顺序
        try:
            build_order = self.resolve_dependencies(PACKS)
            logger.info(
                f"Build order: {[self.get_package_name(url) for url in build_order]}"
            )
        except ValueError as e:
            logger.error(f"Dependency resolution failed: {e}")
            return {}

        # 按顺序构建包（不能并行，因为有依赖关系）
        for url in build_order:
            config = PACKS[url]
            package_name, success, message = self.build_package(url, config)

            self.build_results[package_name] = {
                "url": url,
                "success": success,
                "message": message,
            }

            if not success:
                logger.error(f"Failed to build {package_name}, stopping build process")
                break

        # 最后更新动态链接器缓存
        self.run_command("ldconfig")

        return self.build_results

    def generate_report(self, output_dir: Path):
        """生成构建报告"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 生成JSON报告
        report_file = output_dir / "build_report.json"
        with open(report_file, "w") as f:
            json.dump(self.build_results, f, indent=2)

        # 生成文本报告
        text_report = output_dir / "build_report.txt"
        with open(text_report, "w") as f:
            f.write("Build Report\n")
            f.write("=" * 50 + "\n\n")

            successful = 0
            failed = 0

            for package, result in self.build_results.items():
                status = "SUCCESS" if result["success"] else "FAILED"
                f.write(f"{package}: {status}\n")
                f.write(f"  URL: {result['url']}\n")
                f.write(f"  Message: {result['message']}\n\n")

                if result["success"]:
                    successful += 1
                else:
                    failed += 1

            f.write(f"Summary: {successful} successful, {failed} failed\n")

        # 复制日志文件
        if os.path.exists("build.log"):
            shutil.copy("build.log", output_dir / "build.log")

        logger.info(f"Build report generated in {output_dir}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Build all packages defined in pack.py"
    )
    parser.add_argument(
        "--install-prefix", default="/output", help="Installation prefix"
    )
    parser.add_argument("--build-dir", default="build", help="Build directory")
    parser.add_argument(
        "--output-dir", default="output", help="Output directory for reports"
    )
    parser.add_argument(
        "--max-workers", type=int, default=4, help="Maximum parallel workers"
    )

    args = parser.parse_args()

    try:
        builder = Builder(
            install_prefix=args.install_prefix,
            build_dir=args.build_dir,
            max_workers=args.max_workers,
        )

        results = builder.build_all_packages()
        builder.generate_report(Path(args.output_dir))

        # 打印摘要
        successful = sum(1 for r in results.values() if r["success"])
        total = len(results)

        logger.info(
            f"Build completed: {successful}/{total} packages built successfully"
        )

        if successful == total:
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Build failed with exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
