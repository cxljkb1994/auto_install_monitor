##File: D:\SynologyDrive\SynologyDrive\公司文件\永安期货\08.code\07.Auto_Coder_WorkSpace\03. cdh_trans_script\src\auto_install_prometheus\deploy.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import requests
import argparse
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

from config_loader import ConfigLoader
from deployment_manager import DeploymentManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class PackageInfo:
    """包信息数据类"""
    name: str
    local_path: str
    remote_url: Optional[str] = None

class PackageDownloader:
    """负责下载和管理安装包的类"""
    
    def __init__(self, download_dir: str, http_proxy: Optional[Dict[str, str]] = None):
        self.download_dir = download_dir
        self.logger = logging.getLogger(__name__)
        self.http_proxy = http_proxy

    def download_file(self, url: str, local_path: str, overwrite: bool = False) -> None:
        """
        从远程URL下载文件到本地
        
        Args:
            url: 远程文件URL
            local_path: 本地保存路径
            overwrite: 是否覆盖已存在的文件,默认False
            
        Raises:
            requests.RequestException: 下载失败时抛出
        """
        try:
            # 检查文件是否存在
            if os.path.exists(local_path) and not overwrite:
                self.logger.info(f"文件已存在且未启用覆盖模式,跳过下载: {local_path}")
                return
                
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            # 构建代理配置和SSL验证选项
            proxies = None
            verify_ssl = True
            
            if self.http_proxy:
                if self.http_proxy.get('host') and self.http_proxy.get('port'):
                    proxy_url = f"http://{self.http_proxy['host']}:{self.http_proxy['port']}"
                    proxies = {
                        'http': proxy_url,
                        'https': proxy_url
                    }
                    self.logger.info(f"使用HTTP代理: {proxy_url}")
                
                # 获取SSL验证设置
                verify_ssl = self.http_proxy.get('verify_ssl', True)
                if not verify_ssl:
                    self.logger.warning("SSL证书验证已禁用")
                    # 禁用SSL验证警告
                    import urllib3
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            self.logger.info(f"开始下载文件: {url}")
            response = requests.get(
                url, 
                stream=True, 
                timeout=30, 
                proxies=proxies, 
                verify=verify_ssl
            )
            response.raise_for_status()
            
            with open(local_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            
            self.logger.info(f"文件下载成功: {local_path}")
            
        except requests.RequestException as e:
            self.logger.error(f"文件下载失败: {str(e)}")
            raise

    def prepare_packages(self, packages: Dict[str, str], remote_packages: Dict[str, str], overwrite: bool = False) -> List[PackageInfo]:
        """
        准备所需的安装包
        
        Args:
            packages: 本地包配置
            remote_packages: 远程包配置
            overwrite: 是否覆盖已存在的文件,默认False
            
        Returns:
            List[PackageInfo]: 包信息列表
        """
        package_list = []
        for package_name, local_path in packages.items():
            remote_url = remote_packages.get(package_name)
            package_info = PackageInfo(package_name, local_path, remote_url)
            
            if not os.path.exists(local_path) or overwrite:
                if remote_url:
                    self.download_file(remote_url, local_path, overwrite)
                else:
                    self.logger.warning(f"未找到包 {package_name} 的远程下载地址" + 
                                      ("且本地不存在" if not os.path.exists(local_path) else ""))
            else:
                self.logger.info(f"包 {package_name} 已存在且未启用覆盖模式,跳过下载")
            
            package_list.append(package_info)
        
        return package_list

class ConfigValidator:
    """配置验证器"""
    
    @staticmethod
    def validate_config_path(config_path: str) -> Optional[str]:
        """
        验证配置文件路径
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            Optional[str]: 有效的配置文件路径或None
        """
        if not config_path:
            logger.error("未提供配置文件路径")
            return None
        
        if not os.path.exists(config_path):
            logger.error(f"配置文件不存在: {config_path}")
            return None
        
        return config_path

    @staticmethod
    def validate_download_dir(download_dir: str) -> str:
        """
        验证并创建下载目录
        
        Args:
            download_dir: 下载目录路径
            
        Returns:
            str: 验证后的下载目录路径
        """
        try:
            os.makedirs(download_dir, exist_ok=True)
            return download_dir
        except OSError as e:
            logger.error(f"创建下载目录失败: {str(e)}")
            raise

class DeploymentOrchestrator:
    """部署流程协调器"""
    
    def __init__(self, config_path: str, download_dir: str, overwrite: bool = False):
        self.config_path = config_path
        self.download_dir = download_dir
        self.overwrite = overwrite
        self.logger = logging.getLogger(__name__)
        
    def execute(self) -> None:
        """
        执行部署流程
        
        Raises:
            Exception: 部署过程中的任何错误
        """
        try:
            # 加载配置
            config_loader = ConfigLoader(self.config_path)
            config = config_loader.load_config()
            
            # 准备安装包
            http_proxy = config.get('http_proxy', {})
            downloader = PackageDownloader(self.download_dir, http_proxy)
            packages = downloader.prepare_packages(
                config.get('packages', {}),
                config.get('remote_packages', {}),
                self.overwrite
            )
            
            # 更新配置中的包信息
            self._update_package_paths(config, packages)
            
            # 执行部署
            deployment_manager = DeploymentManager(config)
            deployment_manager.deploy()
            
            self.logger.info("部署流程执行完成")
            
        except Exception as e:
            self.logger.error(f"部署流程执行失败: {str(e)}")
            raise
    
    def _update_package_paths(self, config: Dict[str, Any], packages: List[PackageInfo]) -> None:
        """
        更新配置中的包路径
        
        Args:
            config: 配置字典
            packages: 包信息列表
        """
        config['packages'] = {
            package.name: package.local_path
            for package in packages
        }

def main():
    """程序入口点"""
    parser = argparse.ArgumentParser(description='Prometheus部署工具')
    parser.add_argument('--config-path', default='config.yml', help='配置文件路径')
    parser.add_argument(
        '--download-dir',
        default='installation_packages',
        help='安装包下载目录'
    )
    parser.add_argument(
        '--overwrite',
        type=int,
        default=0,
        choices=[0, 1],
        help='是否覆盖已存在的文件(0:跳过, 1:覆盖), 默认0'
    )
    
    args = parser.parse_args()
    print(args)
    try:
        # 验证配置
        config_path = ConfigValidator.validate_config_path(args.config_path)
        if not config_path:
            sys.exit(1)
            
        download_dir = ConfigValidator.validate_download_dir(args.download_dir)
        
        # 执行部署
        orchestrator = DeploymentOrchestrator(config_path, download_dir, bool(args.overwrite))
        orchestrator.execute()
        
    except Exception as e:
        logger.error(f"部署失败: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()