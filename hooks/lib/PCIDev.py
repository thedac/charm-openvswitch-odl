#!/usr/bin/python
import re
import os
import glob
import subprocess
from charmhelpers.core.decorators import retry_on_exception
import shlex
from charmhelpers.core.hookenv import(
    log,
    config,
)


def format_pci_addr(pci_addr):
    domain, bus, slot_func = pci_addr.split(':')
    slot, func = slot_func.split('.')
    return '{}:{}:{}.{}'.format(domain.zfill(4), bus.zfill(2), slot.zfill(2),
                                func)


class PCINetDevice(object):

    def __init__(self, pci_address):
        self.pci_address = pci_address
        self.update_attributes()

    def update_attributes(self):
        self.update_loaded_kmod()
        self.update_modalias_kmod()
        self.update_interface_info()

    def update_loaded_kmod(self):
        cmd = ['lspci', '-ks', self.pci_address]
        lspci_output = subprocess.check_output(cmd)
        kdrive = None
        for line in lspci_output.split('\n'):
            if 'Kernel driver' in line:
                kdrive = line.split(':')[1].strip()
        log('Loaded kmod for {} is {}'.format(self.pci_address, kdrive))
        self.loaded_kmod = kdrive

    def update_modalias_kmod(self):
        cmd = ['lspci', '-ns', self.pci_address]
        lspci_output = subprocess.check_output(cmd).split()
        vendor_device = lspci_output[2]
        vendor, device = vendor_device.split(':')
        pci_string = 'pci:v{}d{}'.format(vendor.zfill(8), device.zfill(8))
        kernel_name = self.get_kernel_name()
        alias_files = '/lib/modules/{}/modules.alias'.format(kernel_name)
        kmod = None
        with open(alias_files, 'r') as f:
            for line in f.readlines():
                if pci_string in line:
                    kmod = line.split()[-1]
        log('module.alias kmod for {} is {}'.format(self.pci_address, kmod))
        self.modalias_kmod = kmod

    def update_interface_info(self):
        if self.loaded_kmod:
            if self.loaded_kmod == 'igb_uio':
                return self.update_interface_info_vpe()
            else:
                return self.update_interface_info_eth()
        else:
            self.interface_name = None
            self.mac_address = None
            self.state = 'unbound'

    def get_kernel_name(self):
        return subprocess.check_output(['uname', '-r']).strip()

    def pci_rescan(self):
        rescan_file = '/sys/bus/pci/rescan'
        with open(rescan_file, 'w') as f:
            f.write('1')

    def bind(self, kmod):
        bind_file = '/sys/bus/pci/drivers/{}/bind'.format(kmod)
        log('Binding {} to {}'.format(self.pci_address, bind_file))
        with open(bind_file, 'w') as f:
            f.write(self.pci_address)
        self.pci_rescan()
        self.update_attributes()

    def unbind(self):
        if not self.loaded_kmod:
            return
        unbind_file = '/sys/bus/pci/drivers/{}/unbind'.format(self.loaded_kmod)
        log('Unbinding {} from {}'.format(self.pci_address, unbind_file))
        with open(unbind_file, 'w') as f:
            f.write(self.pci_address)
        self.pci_rescan()
        self.update_attributes()

    def update_interface_info_vpe(self):
        vpe_devices = self.get_vpe_interfaces_and_macs()
        device_info = {}
        for interface in vpe_devices:
            if self.pci_address == interface['pci_address']:
                device_info['interface'] = interface['interface']
                device_info['macAddress'] = interface['macAddress']
        if device_info:
            self.interface_name = device_info['interface']
            self.mac_address = device_info['macAddress']
            self.state = 'vpebound'
        else:
            self.interface_name = None
            self.mac_address = None
            self.state = None

    @retry_on_exception(5, base_delay=10,
                        exc_type=subprocess.CalledProcessError)
    def get_vpe_cli_out(self):
        echo_cmd = [
            'echo', '-e', 'show interfaces-state interface phys-address\nexit']
        cli_cmd = ['/opt/cisco/vpe/bin/confd_cli', '-N', '-C', '-u', 'system']
        echo = subprocess.Popen(echo_cmd, stdout=subprocess.PIPE)
        cli_output = subprocess.check_output(cli_cmd, stdin=echo.stdout)
        echo.wait()
        echo.terminate
        log('confd_cli: ' + cli_output)
        return cli_output

    def get_vpe_interfaces_and_macs(self):
        cli_output = self.get_vpe_cli_out()
        vpe_devs = []
        if 'local0' not in cli_output:
            log('local0 missing from confd_cli output, assuming things went '
                'wrong')
            raise subprocess.CalledProcessError
        for line in cli_output.split('\n'):
            if re.search(r'([0-9A-F]{2}[:-]){5}([0-9A-F]{2})', line, re.I):
                interface, mac = line.split()
                pci_addr = self.extract_pci_addr_from_vpe_interface(interface)
                vpe_devs.append({
                    'interface': interface,
                    'macAddress': mac,
                    'pci_address': pci_addr,
                })
        return vpe_devs

    def extract_pci_addr_from_vpe_interface(self, nic):
        ''' Convert a str from nic postfix format to padded format

        eg 6/1/2 -> 0000:06:01.2'''
        log('Extracting pci address from {}'.format(nic))
        # addr = re.sub(r'^\D*', '', nic, re.IGNORECASE)
        addr = re.sub(r'^.*Ethernet', '', nic, re.IGNORECASE)
        bus, slot, func = addr.split('/')
        domain = '0000'
        pci_addr = format_pci_addr(
            '{}:{}:{}.{}'.format(domain, bus, slot, func))
        log('pci address for {} is {}'.format(nic, pci_addr))
        return pci_addr

    def update_interface_info_eth(self):
        net_devices = self.get_sysnet_interfaces_and_macs()
        for interface in net_devices:
            if self.pci_address == interface['pci_address']:
                self.interface_name = interface['interface']
                self.mac_address = interface['macAddress']
                self.state = interface['state']

    def get_sysnet_interfaces_and_macs(self):
        net_devs = []
        for sdir in glob.glob('/sys/class/net/*'):
            sym_link = sdir + "/device"
            if os.path.islink(sym_link):
                fq_path = os.path.realpath(sym_link)
                path = fq_path.split('/')
                if 'virtio' in path[-1]:
                    pci_address = path[-2]
                else:
                    pci_address = path[-1]
                net_devs.append({
                    'interface': self.get_sysnet_interface(sdir),
                    'macAddress': self.get_sysnet_mac(sdir),
                    'pci_address': pci_address,
                    'state': self.get_sysnet_device_state(sdir),
                })
        return net_devs

    def get_sysnet_mac(self, sysdir):
        mac_addr_file = sysdir + '/address'
        with open(mac_addr_file, 'r') as f:
            read_data = f.read()
        mac = read_data.strip()
        log('mac from {} is {}'.format(mac_addr_file, mac))
        return mac

    def get_sysnet_device_state(self, sysdir):
        state_file = sysdir + '/operstate'
        with open(state_file, 'r') as f:
            read_data = f.read()
        state = read_data.strip()
        log('state from {} is {}'.format(state_file, state))
        return state

    def get_sysnet_interface(self, sysdir):
        return sysdir.split('/')[-1]


class PCINetDevices(object):

    def __init__(self):
        pci_addresses = self.get_pci_ethernet_addresses()
        self.pci_devices = [PCINetDevice(dev) for dev in pci_addresses]

    def get_pci_ethernet_addresses(self):
        cmd = ['lspci', '-m', '-D']
        lspci_output = subprocess.check_output(cmd)
        pci_addresses = []
        for line in lspci_output.split('\n'):
            columns = shlex.split(line)
            if len(columns) > 1 and columns[1] == 'Ethernet controller':
                pci_address = columns[0]
                pci_addresses.append(format_pci_addr(pci_address))
        return pci_addresses

    def update_devices(self):
        for pcidev in self.pci_devices:
            pcidev.update_attributes()

    def get_macs(self):
        macs = []
        for pcidev in self.pci_devices:
            if pcidev.mac_address:
                macs.append(pcidev.mac_address)
        return macs

    def get_device_from_mac(self, mac):
        for pcidev in self.pci_devices:
            if pcidev.mac_address == mac:
                return pcidev

    def get_device_from_pci_address(self, pci_addr):
        for pcidev in self.pci_devices:
            if pcidev.pci_address == pci_addr:
                return pcidev

    def rebind_orphans(self):
        self.unbind_orphans()
        self.bind_orphans()

    def unbind_orphans(self):
        for orphan in self.get_orphans():
            orphan.unbind()
        self.update_devices()

    def bind_orphans(self):
        for orphan in self.get_orphans():
            orphan.bind(orphan.modalias_kmod)
        self.update_devices()

    def get_orphans(self):
        orphans = []
        for pcidev in self.pci_devices:
            if not pcidev.loaded_kmod or pcidev.loaded_kmod == 'igb_uio':
                if not pcidev.interface_name and not pcidev.mac_address:
                    orphans.append(pcidev)
        return orphans


class PCIInfo(dict):

    def __init__(self):
        ''' Generate pci info '''
        if not self.is_ready():
            log('PCIInfo not ready')
            return
        self.user_requested_config = self.get_user_requested_config()
        net_devices = PCINetDevices()
        self['local_macs'] = net_devices.get_macs()
        pci_addresses = []
        self['local_config'] = {}
        for mac in self.user_requested_config.keys():
            log('Checking if {} is on this host'.format(mac))
            if mac in self['local_macs']:
                log('{} is on this host'.format(mac))
                device = net_devices.get_device_from_mac(mac)
                log('{} is {} and is currently {}'.format(mac,
                    device.pci_address, device.interface_name))
                if device.state == 'up':
                    log('Refusing to add {} to device list as it is {}'.format(
                        device.pci_address, device.state))
                else:
                    pci_addresses.append(device.pci_address)
                    self['local_config'][mac] = []
                    for conf in self.user_requested_config[mac]:
                        self['local_config'][mac].append({
                            'net': conf.get('net'),
                            'interface': device.interface_name,
                        })
        if pci_addresses:
            self['pci_devs'] = 'dev ' + ' dev '.join(pci_addresses)
        else:
            self['pci_devs'] = 'no-pci'
        log('pci_devs {}'.format(self['pci_devs']))

    def is_ready(self):
        '''Override this for SDN specific integrations'''
        return True

    def get_user_requested_config(self):
        ''' Parse the user requested config str
        mac=<mac>;net=<net>;vlan=<vlan> and return a dict'''
        mac_net_config = {}
        mac_map = config('mac-network-map')
        if mac_map:
            for line in mac_map.split():
                entries = line.split(';')
                tmp_dict = {}
                for entry in entries:
                    if '=' in entry:
                        key, value = entry.split('=')
                        tmp_dict[key] = value
                keys = tmp_dict.keys()
                if 'mac' in keys:
                    if tmp_dict['mac'] in mac_net_config:
                        mac_net_config[tmp_dict['mac']].append({
                            'net': tmp_dict.get('net'),
                        })
                    else:
                        mac_net_config[tmp_dict['mac']] = [{
                            'net': tmp_dict.get('net'),
                        }]
        return mac_net_config
