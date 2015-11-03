import subprocess

from socket import gethostname

import lib.ODL as ODL
import lib.PCIDev as PCIDev
import lib.ovs as ovs

from charmhelpers.contrib.network.ip import get_address_in_network
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import log
from charmhelpers.core.hookenv import status_set
from charmhelpers.core.hookenv import unit_private_ip
from charmhelpers.core.reactive import hook
from charmhelpers.core.reactive import when
from charmhelpers.core.reactive import when_not
from charmhelpers.core.unitdata import kv

from charmhelpers.fetch import apt_install
from charmhelpers.fetch import apt_purge
from charmhelpers.fetch import filter_installed_packages

# Packages to install/remove
PACKAGES = ['openvswitch-switch']


@when('ovsdb-manager.access.available')
def configure_openvswitch(odl_ovsdb):
    db = kv()
    # NOTE(jamespage): Check connection string as well
    #                  broken/departed seems busted right now
    if db.get('installed') and odl_ovsdb.connection_string():
        log("Configuring OpenvSwitch with ODL OVSDB controller: %s" %
            odl_ovsdb.connection_string())
        local_ip = get_address_in_network(config('os-data-network'),
                                          unit_private_ip())
        ovs.set_config('local_ip', local_ip)
        ovs.set_config('controller-ips', odl_ovsdb.private_address(),
                       table='external_ids')
        ovs.set_config('host-id', gethostname(),
                       table='external_ids')
        ovs.set_manager(odl_ovsdb.connection_string())
        status_set('active', 'Open vSwitch configured and ready')


@when_not('ovsdb-manager.access.available')
def unconfigure_openvswitch(odl_ovsdb=None):
    db = kv()
    if db.get('installed'):
        log("Unconfiguring OpenvSwitch")
        subprocess.check_call(['ovs-vsctl', 'del-manager'])
        bridges = subprocess.check_output(['ovs-vsctl',
                                           'list-br']).split()
        for bridge in bridges:
            subprocess.check_call(['ovs-vsctl',
                                   'del-controller', bridge])
        status_set('waiting',
                   'Open vSwitch not configured with an ODL OVSDB controller')


@when_not('ovsdb-manager.connected')
def no_ovsdb_manager(odl_ovsdb=None):
    status_set('blocked', 'Not related to an OpenDayLight OVSDB controller')


@when('neutron-plugin.connected')
def configure_neutron_plugin(neutron_plugin):
    neutron_plugin.configure_plugin(
        plugin='ovs-odl',
        config={
            "nova-compute": {
                "/etc/nova/nova.conf": {
                    "sections": {
                        'DEFAULT': [
                            ('firewall_driver',
                             'nova.virt.firewall.'
                             'NoopFirewallDriver'),
                            ('libvirt_vif_driver',
                             'nova.virt.libvirt.vif.'
                             'LibvirtGenericVIFDriver'),
                            ('security_group_api', 'nova'),
                        ],
                    }
                }
            }
        })


@hook('install')
def install_packages():
    db = kv()
    if not db.get('installed'):
        status_set('maintenance', 'Installing packages')
        apt_install(filter_installed_packages(PACKAGES))
        db.set('installed', True)


@hook('stop')
def uninstall_packages():
    db = kv()
    if db.get('installed'):
        status_set('maintenance', 'Purging packages')
        apt_purge(PACKAGES)
        db.unset('installed')


@when('controller-api.access.available')
def odl_node_registration(controller=None):
    """ Register node with ODL if not registered already """
    if controller and controller.connection():
        odl = ODL.ODLConfig(**controller.connection())
        device_name = gethostname()
        if odl.is_device_registered(device_name):
            log('{} is already registered in odl'.format(device_name))
        else:
            local_ip = get_address_in_network(config('os-data-network'),
                                              unit_private_ip())
            log('Registering {} ({}) in odl'.format(
                device_name, local_ip))
            odl.odl_register_node(device_name, local_ip)


@when('controller-api.access.available')
def odl_register_macs(controller=None):
    """ Register local interfaces and their networks with ODL """
    if controller and controller.connection():
        log('Looking for macs to register with networks in odl')
        odl = ODL.ODLConfig(**controller.connection())
        device_name = gethostname()
        requested_config = PCIDev.PCIInfo()['local_config']
        for mac in requested_config.keys():
            for requested_net in requested_config[mac]:
                net = requested_net['net']
                interface = requested_net['interface']
                if not odl.is_net_device_registered(net, device_name,
                                                    interface, mac,
                                                    device_type='ovs'):
                    log('Registering {} and {} on '
                        '{}'.format(net, interface, mac))
                    odl.odl_register_macs(device_name, net, interface, mac,
                                          device_type='ovs')
                else:
                    log('{} already registered for {} on '
                        '{}'.format(net, interface, device_name))
