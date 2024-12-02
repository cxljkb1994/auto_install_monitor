import os
import yaml
import logging
import subprocess
import sys
import paramiko
from typing import Dict, Any, List

class DeploymentManager:
    def __init__(self, config: Dict[str, Any]):
        """
        初始化部署管理器
        
        :param config: 配置字典
        """
        self.config = config
        self.base_dir = config.get('deployment_base_dir', '/opt/monitor_deployment')
        self.logger = logging.getLogger(__name__)
        self.file_transfer_config = config.get('file_transfer', {})
    
    def prep_deployment_dir(self):
        """
        准备部署目录
        """
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, 'packages'), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, 'configs'), exist_ok=True)
        self.logger.info(f"已创建部署目录: {self.base_dir}")
    
    def generate_inventory(self) -> str:
        """
        生成Ansible主机清单文件,根据部署模式生成不同的清单
        
        :return: 清单文件路径
        """
        inventory_path = os.path.join(
            self.base_dir, 
            'configs', 
            'hosts'
        )
        
        target_servers = self.config.get('target_servers', {})
        cluster_mode = self.config.get('prometheus_deployment', {}).get('cluster_mode', 0)
        
        with open(inventory_path, 'w') as f:
            # Prometheus master节点组
            f.write("[prometheus_master]\n")
            for server in target_servers.get('prometheus_servers', {}).get('master', []):
                f.write(f"{server['ip']} ansible_ssh_user={server.get('ssh_user', 'root')} "
                       f"ansible_ssh_pass={server.get('ssh_password', '')} prometheus_role=master\n")
            
            # 仅在集群模式下添加slave节点
            if cluster_mode == 1:
                f.write("\n[prometheus_slave]\n")
                for server in target_servers.get('prometheus_servers', {}).get('slave', []):
                    f.write(f"{server['ip']} ansible_ssh_user={server.get('ssh_user', 'root')} "
                           f"ansible_ssh_pass={server.get('ssh_password', '')} prometheus_role=slave\n")
            
            # Node Exporter节点组
            f.write("\n[node_exporter_servers]\n")
            for server in target_servers.get('node_exporter_servers', []):
                f.write(f"{server['ip']} ansible_ssh_user={server.get('ssh_user', 'root')} "
                       f"ansible_ssh_pass={server.get('ssh_password', '')}\n")
            
            # Grafana节点组
            f.write("\n[grafana_servers]\n")
            for server in target_servers.get('grafana_servers', []):
                f.write(f"{server['ip']} ansible_ssh_user={server.get('ssh_user', 'root')} "
                       f"ansible_ssh_pass={server.get('ssh_password', '')}\n")
            
            # 定义Prometheus集群组
            f.write("\n[prometheus_cluster:children]\n")
            f.write("prometheus_master\n")
            f.write("prometheus_slave\n")

        self.logger.info(f"已生成主机清单文件: {inventory_path}")
        return inventory_path
    
    def generate_prometheus_config(self) -> str:
        """
        生成Prometheus配置文件
        
        :return: 配置文件路径
        """
        prometheus_config_path = os.path.join(
            self.base_dir, 
            'configs', 
            'prometheus.yml'
        )
        with open(prometheus_config_path, 'w') as f:
            yaml.dump(self.config['prometheus_config'], f, default_flow_style=False)
        
        return prometheus_config_path
    
    def generate_grafana_config(self) -> str:
        """
        生成Grafana配置文件
        
        :return: 配置文件路径
        """
        grafana_config_path = os.path.join(
            self.base_dir, 
            'configs', 
            'grafana.ini'
        )
        with open(grafana_config_path, 'w') as f:
            yaml.dump(self.config['grafana_config'], f, default_flow_style=False)
        
        return grafana_config_path
    
    def generate_prometheus_playbook(self) -> str:
        """
        生成Prometheus部署Playbook,支持集群配置
        
        :return: Playbook文件路径
        """
        playbook_path = os.path.join(
            self.base_dir, 
            'configs', 
            'prometheus_deploy.yml'
        )
        
        # 基础变量定义
        base_vars = {
            'prometheus_package': "/app/"+self.config['packages']['prometheus']
        }
        
        # 生成playbook内容
        playbook = [
            # Prometheus Master节点部署
            {
                'hosts': 'prometheus_master',
                'become': 'yes',
                'vars': {
                    **base_vars,
                    'is_master': True
                },
                'tasks': self._generate_prometheus_tasks(is_master=True)
            },
            # Prometheus Slave节点部署
            {
                'hosts': 'prometheus_slave',
                'become': 'yes',
                'vars': {
                    **base_vars,
                    'is_master': False
                },
                'tasks': self._generate_prometheus_tasks(is_master=False)
            }
        ]
        
        with open(playbook_path, 'w') as f:
            yaml.dump(playbook, f, default_flow_style=False)
        
        # 生成所需的服务文件
        self._generate_prometheus_service_file()
        return playbook_path
        
    def generate_node_exporter_playbook(self) -> str:
        """
        生成Node Exporter部署Playbook
        
        :return: Playbook文件路径
        """
        playbook_path = os.path.join(
            self.base_dir,
            'configs',
            'node_exporter_deploy.yml'
        )
        
        # 生成playbook内容
        playbook = [
            {
                'hosts': 'node_exporter_servers',
                'become': 'yes',
                'vars': {
                    'node_exporter_package': "/app/"+self.config['packages']['node_exporter']
                },
                'tasks': self._generate_node_exporter_tasks()
            }
        ]
        
        with open(playbook_path, 'w') as f:
            yaml.dump(playbook, f, default_flow_style=False)
            
        # 生成服务文件
        self._generate_node_exporter_service_file()
        return playbook_path
    
    def _generate_node_exporter_service_file(self):
        """
        生成Node Exporter systemd服务文件
        """
        service_path = os.path.join(
            self.base_dir, 
            'configs', 
            'node_exporter.service'
        )
        with open(service_path, 'w') as f:
            f.write("""[Unit]
Description=Node Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=root
ExecStart=/usr/local/node_exporter/node_exporter
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=20s
Restart=always

[Install]
WantedBy=multi-user.target
""")

    def _generate_node_exporter_tasks(self) -> List[Dict[str, Any]]:
        """
        生成Node Exporter部署任务
        
        :return: 任务列表
        """
        return [
            {
                'name': 'Check if Node Exporter is installed',
                'command': 'which node_exporter',
                'register': 'node_exporter_installed',
                'ignore_errors': True
            },
            {
                'block': [
                    {
                        'name': 'Copy Node Exporter package',
                        'copy': {
                            'src': '{{ node_exporter_package }}',
                            'dest': '/tmp/node_exporter.tar.gz'
                        }
                    },
                    {
                        'name': 'Extract Node Exporter',
                        'unarchive': {
                            'src': '/tmp/node_exporter.tar.gz',
                            'dest': '/usr/local/',
                            'remote_src': True
                        }
                    }
                ],
                'when': 'node_exporter_installed.rc != 0'
            },
            {
                'name': 'Create symlink for Node Exporter directory',
                'file': {
                    'src': '/usr/local/node_exporter-1.8.2.linux-amd64',
                    'dest': '/usr/local/node_exporter',
                    'state': 'link',
                    'force': 'yes'
                }
            },
            {
                'name': 'Create Node Exporter systemd service',
                'template': {
                    'src': '{{ playbook_dir }}/node_exporter.service',
                    'dest': '/etc/systemd/system/node_exporter.service'
                }
            },
            {
                'name': 'Start Node Exporter service',
                'systemd': {
                    'name': 'node_exporter',
                    'state': 'restarted',
                    'daemon_reload': True,
                    'enabled': True
                }
            }
        ]

    def _generate_prometheus_tasks(self, is_master: bool = True) -> List[Dict[str, Any]]:
        """
        生成Prometheus和Node Exporter部署任务
        
        :return: 任务列表
        """

        # 然后是Prometheus的任务
        prometheus_tasks = [
            {
                'name': 'Check if Prometheus is installed',
                'command': 'which prometheus',
                'register': 'prometheus_installed',
                'ignore_errors': True
            },
            {
                'block': [
                    {
                        'name': 'Copy Prometheus package',
                        'copy': {
                            'src': '{{ prometheus_package }}',
                            'dest': '/tmp/prometheus.tar.gz'
                        }
                    },
                    {
                        'name': 'Extract Prometheus',
                        'unarchive': {
                            'src': '/tmp/prometheus.tar.gz',
                            'dest': '/usr/local/',
                            'remote_src': True
                        }
                    }
                ],
                'when': 'prometheus_installed.rc != 0'
            },
            {
                'name': 'Create symlink for Grafana directory',
                'file': {
                    'src': '/usr/local/prometheus-3.0.1.linux-amd64',
                    'dest': '/usr/local/prometheus',
                    'state': 'link',
                    'force':  'yes'
                }
            },
            {
                'name': 'Ensure the Prometheus directory exists',
                'file': {
                    'path': '/usr/local/prometheus',
                    'state': 'directory',
                    'mode':'0755'
                }
            },
            {
                'name': 'Copy Prometheus configuration',
                'template': {
                    'src': '{{ playbook_dir }}/prometheus.yml',
                    'dest': '/usr/local/prometheus/prometheus.yml'
                }
            },
            {
                'name': 'Create Prometheus systemd service',
                'template': {
                    'src': '{{ playbook_dir }}/prometheus.service',
                    'dest': '/etc/systemd/system/prometheus.service'
                }
            },
            {
                'name': 'Start Prometheus service',
                'systemd': {
                    'name': 'prometheus',
                    'state': 'restarted',
                    'daemon_reload': True,
                    'enabled': True
                }
            }
        ]
        
        # 返回所有任务列表
        return prometheus_tasks
    
    def _generate_prometheus_service_file(self):
        """
        生成Prometheus systemd服务文件
        """
        service_path = os.path.join(
            self.base_dir, 
            'configs', 
            'prometheus.service'
        )
        with open(service_path, 'w') as f:
            f.write("""[Unit]
Description=Prometheus
Wants=network-online.target
After=network-online.target

[Service]
User=root
ExecStart=/usr/local/prometheus/prometheus --config.file=/usr/local/prometheus/prometheus.yml
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=20s
Restart=always

[Install]
WantedBy=multi-user.target
""")
    
    def generate_grafana_playbook(self) -> str:
        """
        生成Grafana部署Playbook
        
        :return: Playbook文件路径
        """
        playbook_path = os.path.join(
            self.base_dir, 
            'configs', 
            'grafana_deploy.yml'
        )
        
        playbook = [
            {
                'hosts': 'grafana_servers',
                'become': 'yes',
                'vars': {
                    'grafana_package': "/app/"+self.config['packages']['grafana']
                },
                'tasks': self._generate_grafana_tasks()
            }
        ]
        
        with open(playbook_path, 'w') as f:
            yaml.dump(playbook, f, default_flow_style=False)
        
        return playbook_path
    
    def _generate_grafana_tasks(self) -> List[Dict[str, Any]]:
        """
        生成Grafana部署任务
        
        :return: 任务列表
        """
        return [
            {
                'name': 'Check if Grafana is installed',
                'command': 'which grafana-server',
                'register': 'grafana_installed',
                'ignore_errors': True
            },
            {
                'block': [
                    {
                        'name': 'Copy Grafana package',
                        'copy': {
                            'src': '{{ grafana_package }}',
                            'dest': '/tmp/grafana.tar.gz'
                        }
                    },
                    {
                        'name': 'Extract Grafana',
                        'unarchive': {
                            'src': '/tmp/grafana.tar.gz',
                            'dest': '/usr/local/',
                            'remote_src': True
                        }
                    }
                ],
                'when': 'grafana_installed.rc != 0'
            },
            {
                'name': 'Create symlink for Grafana directory',
                'file': {
                    'src': '/usr/local/grafana-v11.3.1',
                    'dest': '/usr/local/grafana',
                    'state': 'link',
                    'force':  'yes'
                }
            },

            {
                'name': 'Ensure Grafana config directory exists',
                'file': {
                    'path': '/usr/local/grafana/conf',
                    'state': 'directory',
                    'mode': '0755'
                }
            },
            {
                'name': 'Copy Grafana configuration',
                'template': {
                    'src': '{{ playbook_dir }}/grafana.ini',
                    'dest': '/usr/local/grafana/conf/grafana.ini'
                }
            },
            {
   'name': 'Create Grafana systemd service file',
                'copy': {
                    'content': """[Unit]
Description=Grafana
Documentation=http://docs.grafana.org
Wants=network-online.target
After=network-online.target

[Service]
User=root
WorkingDirectory=/usr/local/grafana
ExecStart=/usr/local/grafana/bin/grafana-server --config=/usr/local/grafana/conf/grafana.ini
Restart=always

[Install]
WantedBy=multi-user.target""",
                    'dest': '/etc/systemd/system/grafana.service',
                    'mode': '0644'
                }
            },
            {
                'name': 'Start Grafana service',
                'systemd': {
                    'name': 'grafana',
                    'state': 'restarted',
                    'daemon_reload': True,
                    'enabled': True
                }
            }
        ]
    
    def transfer_installation_packages(self, overwrite: int = 0):
        """
        通过SSH传输安装包到目标服务器
        
        Args:
            overwrite: 是否覆盖已存在的文件(0:跳过, 1:覆盖), 默认0
        """
        try:
            # 连接源服务器
            source_server = self.file_transfer_config.get('source_server', {})
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=source_server['ip'], 
                username=source_server['ssh_user'], 
                password=source_server['ssh_password']
            )

            sftp = client.open_sftp()
            
            # 获取远程目标路径
            remote_path = self.file_transfer_config.get('remote_path', '/opt/installation_packages')
            
            # 检查并创建远程目录
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                self.logger.info(f"远程目录 {remote_path} 不存在，正在创建...")
                # 递归创建目录
                current_path = '/'
                for dir_part in remote_path.strip('/').split('/'):
                    current_path = f"{current_path}{dir_part}/"
                    try:
                        sftp.stat(current_path)
                    except FileNotFoundError:
                        sftp.mkdir(current_path)
                self.logger.info(f"成功创建远程目录: {remote_path}")

            # 定义需要传输的包
            packages = {
                'prometheus': {
                    'local_path': self.config['packages']['prometheus'],
                    'remote_path': f"{remote_path}/prometheus.tar.gz"
                },
                'node_exporter': {
                    'local_path': self.config['packages']['node_exporter'],
                    'remote_path': f"{remote_path}/node_exporter.tar.gz"
                },
                'grafana': {
                    'local_path': self.config['packages']['grafana'],
                    'remote_path': f"{remote_path}/grafana.tar.gz"
                }
            }
            
            # 传输每个包
            for package_name, package_info in packages.items():
                local_path = package_info['local_path']
                remote_path = package_info['remote_path']
                
                try:
                    # 检查远程文件是否存在
                    try:
                        sftp.stat(remote_path)
                        file_exists = True
                    except FileNotFoundError:
                        file_exists = False
                    
                    # 根据文件存在状态和覆盖参数决定是否传输
                    if not file_exists or overwrite:
                        self.logger.info(f"开始传输 {package_name} 包到 {remote_path}")
                        sftp.put(local_path, remote_path)
                        self.logger.info(f"{package_name} 包传输完成")
                    else:
                        self.logger.info(f"{package_name} 包已存在且未启用覆盖模式，跳过传输")
                        
                except Exception as e:
                    self.logger.error(f"{package_name} 包传输失败: {str(e)}")
                    raise

            sftp.close()
            client.close()

            self.logger.info("安装包传输完成")
        except Exception as e:
            self.logger.error(f"安装包传输失败: {e}")
            sys.exit(1)

    def deploy(self):
        """
        执行部署
        """
        try:
            # 传输安装包，使用配置中的 overwrite 参数
            overwrite = self.config.get('overwrite', 0)
            self.transfer_installation_packages(overwrite)

            # 准备部署目录
            self.prep_deployment_dir()
            
            # 生成主机清单
            inventory_path = self.generate_inventory()
            self.logger.info(f"生成主机清单: {inventory_path}")
            
            # 生成配置文件
            self.generate_prometheus_config()
            self.generate_grafana_config()
            
            # 生成部署Playbook
            prometheus_playbook = self.generate_prometheus_playbook()
            self.logger.info(f"生成Prometheus部署Playbook: {prometheus_playbook}")
            
            grafana_playbook = self.generate_grafana_playbook()
            self.logger.info(f"生成Grafana部署Playbook: {grafana_playbook}")
            
            # 生成node exporter的playbook
            node_exporter_playbook = self.generate_node_exporter_playbook()
            self.logger.info(f"生成Node Exporter部署Playbook: {node_exporter_playbook}")

            # 根据部署模式执行不同的部署命令
            cluster_mode = self.config.get('prometheus_deployment', {}).get('cluster_mode', 0)
            
            if cluster_mode == 1:
                # 集群模式部署
                deploy_commands = [
                    f"ansible-playbook -i {inventory_path} {node_exporter_playbook}",
                    f"ansible-playbook -i {inventory_path} {prometheus_playbook}",
                    f"ansible-playbook -i {inventory_path} {grafana_playbook}"
                ]
                self.logger.info("开始集群模式部署监控组件...")
            else:
                # 单机模式部署，只针对master节点
                deploy_commands = [
                    f"ansible-playbook -i {inventory_path} {node_exporter_playbook}",
                    f"ansible-playbook -i {inventory_path} {prometheus_playbook} --limit prometheus_master",
                    f"ansible-playbook -i {inventory_path} {grafana_playbook}"
                ]
                self.logger.info("开始单机模式部署监控组件...")
            
            for cmd in deploy_commands:
                self.logger.info(f"执行命令: {cmd}")
                try:
                    result = subprocess.run(
                        cmd, 
                        shell=True, 
                        check=True,
                        capture_output=True, 
                        text=True
                    )
                    self.logger.info("命令输出:")
                    self.logger.info(result.stdout)
                except subprocess.CalledProcessError as e:
                    self.logger.error(f"部署命令执行失败: {e}")
                    self.logger.error("标准输出:")
                    self.logger.error(result.stdout)
                    self.logger.error("错误输出:")
                    self.logger.error(e.stderr)
                    raise
            
            self.logger.info("部署完成！")
        
        except subprocess.CalledProcessError as e:
            self.logger.error(f"部署失败: {e}")
            self.logger.error(f"错误输出: {e.stderr}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"部署过程中发生未知错误: {e}")
            sys.exit(1)