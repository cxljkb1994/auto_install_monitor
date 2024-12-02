#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import yaml
import logging
from typing import Dict, Any

class ConfigLoader:
    def __init__(self, config_path: str):
        """
        初始化配置加载器
        
        :param config_path: 配置文件路径
        """
        self.config_path = config_path
        self.logger = logging.getLogger(__name__)
    
    def validate_config(self, config: Dict[str, Any]):
        """
        验证配置文件的完整性
        
        :param config: 配置字典
        """
        required_keys = [
            'deployment_base_dir', 
            'packages', 
            'target_servers',
            'prometheus_config',
            'grafana_config',
            'prometheus_deployment',
            'file_transfer',
            'http_proxy',
            'remote_packages'
        ]
        
        for key in required_keys:
            if key not in config:
                raise ValueError(f"配置文件中缺少必要的配置项: {key}")
        
        # 验证Prometheus部署模式配置
        prometheus_deployment = config.get('prometheus_deployment', {})
        cluster_mode = prometheus_deployment.get('cluster_mode')
        if cluster_mode not in [0, 1]:
            raise ValueError("prometheus_deployment.cluster_mode 必须为 0 或 1")
        
        # 验证目标服务器配置
        target_servers = config.get('target_servers', {})
        prometheus_servers = target_servers.get('prometheus_servers', {})
        
        # 检查master节点配置
        if not prometheus_servers.get('master'):
            raise ValueError("配置文件中缺少 prometheus_servers.master 配置")
            
        # 如果是集群模式，检查slave节点配置
        if cluster_mode == 1 and not prometheus_servers.get('slave'):
            raise ValueError("集群模式下配置文件中缺少 prometheus_servers.slave 配置")
            
        # 验证必需的服务器组
        required_server_groups = ['node_exporter_servers', 'grafana_servers']
        for group in required_server_groups:
            if not target_servers.get(group):
                raise ValueError(f"配置文件中缺少 {group} 配置")

        # 验证服务器配置的完整性
        def validate_server_config(server_list, group_name):
            if not isinstance(server_list, list):
                server_list = [server_list]
            for server in server_list:
                if not all(key in server for key in ['ip', 'ssh_user', 'ssh_password']):
                    raise ValueError(f"{group_name} 中的服务器配置缺少必要的字段(ip/ssh_user/ssh_password)")

        # 验证各个服务器组的配置
        for master_server in prometheus_servers.get('master', []):
            validate_server_config(master_server, 'prometheus_servers.master')
            
        if cluster_mode == 1:
            for slave_server in prometheus_servers.get('slave', []):
                validate_server_config(slave_server, 'prometheus_servers.slave')
                
        for group in required_server_groups:
            validate_server_config(target_servers[group], group)

        # 验证文件传输配置
        file_transfer = config.get('file_transfer', {})
        if not all(key in file_transfer for key in ['source_server', 'remote_path']):
            raise ValueError("file_transfer 配置缺少必要的字段")
            
        source_server = file_transfer.get('source_server', {})
        if not all(key in source_server for key in ['ip', 'ssh_user', 'ssh_password']):
            raise ValueError("file_transfer.source_server 配置缺少必要的字段")

        # 验证包配置
        packages = config.get('packages', {})
        remote_packages = config.get('remote_packages', {})
        required_packages = ['prometheus', 'node_exporter', 'grafana']
        
        for package in required_packages:
            if package not in packages:
                raise ValueError(f"packages 配置缺少 {package}")
            if package not in remote_packages:
                raise ValueError(f"remote_packages 配置缺少 {package}")
    
    def load_config(self) -> Dict[str, Any]:
        """
        读取并验证配置文件
        
        :return: 配置字典
        """
        # 检查配置文件是否存在
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"配置文件 {self.config_path} 不存在")
            
        # 读取主配置文件
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                try:
                    config = yaml.safe_load(content)
                except yaml.YAMLError as e:
                    self.logger.error(f"配置文件内容:\n{content}")
                    self.logger.error(f"配置文件解析错误: {str(e)}")
                    raise
        except UnicodeDecodeError as e:
            self.logger.error(f"配置文件编码错误: {str(e)}")
            raise

        # 读取密钥文件
        secrets_file = config.get('server_secrets_file')
        if not secrets_file:
            raise ValueError("未在配置文件中指定 server_secrets_file")
            
        secrets_path = os.path.join(os.path.dirname(self.config_path), secrets_file)
        if not os.path.exists(secrets_path):
            raise FileNotFoundError(f"密钥文件 {secrets_path} 不存在")
            
        try:
            with open(secrets_path, 'r', encoding='utf-8') as f:
                secrets = yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"读取密钥文件失败: {str(e)}")
            raise

        # 合并服务器凭据到配置中
        self._merge_server_credentials(config, secrets.get('server_credentials', {}))
        
        # 验证配置
        self.validate_config(config)
        
        return config

    def _merge_server_credentials(self, config: Dict[str, Any], credentials: Dict[str, Any]):
        """
        将服务器凭据合并到配置中
        
        Args:
            config: 主配置字典
            credentials: 服务器凭据字典
        """
        # 合并 Prometheus 服务器凭据
        for role in ['master', 'slave']:
            servers = credentials.get('prometheus', {}).get(role, [])
            for server in servers:
                for target in config['target_servers']['prometheus_servers'].get(role, []):
                    if target['ip'] == server['ip']:
                        target['ssh_password'] = server['ssh_password']

        # 合并 Node Exporter 服务器凭据
        for server in credentials.get('node_exporter', []):
            for target in config['target_servers']['node_exporter_servers']:
                if target['ip'] == server['ip']:
                    target['ssh_password'] = server['ssh_password']

        # 合并 Grafana 服务器凭据
        for server in credentials.get('grafana', []):
            for target in config['target_servers']['grafana_servers']:
                if target['ip'] == server['ip']:
                    target['ssh_password'] = server['ssh_password']

        # 合并源服务器凭据
        source_creds = credentials.get('source')
        if source_creds:
            config['file_transfer']['source_server']['ssh_password'] = source_creds['ssh_password']