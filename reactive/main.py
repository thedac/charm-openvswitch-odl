from charmhelpers.core.hookenv import status_set
from charms.reactive import (
    when,
    when_not,
)

from charmhelpers.contrib.openstack.utils import os_release

from charmfactory import OpenvswitchODLCharmFactory, OS_CHARM_NAME

charm = None

installed_state = '{}-installed'.format(OS_CHARM_NAME)
configured_state = '{}-openvswitch-configured'.format(OS_CHARM_NAME)


def get_charm():
    global charm
    if charm is None:
        charm = OpenvswitchODLCharmFactory.charm(
            release=os_release('neutron-common', base='icehouse'))
    return charm


@when_not(installed_state)
def install_packages():
    get_charm().install()


@when('ovsdb-manager.access.available', installed_state)
def configure_openvswitch(odl_ovsdb):
    get_charm().configure_openvswitch(odl_ovsdb)


@when_not('ovsdb-manager.access.available')
def unconfigure_openvswitch(odl_ovsdb=None):
    get_charm().unconfigure_openvswitch(odl_ovsdb)
    status_set('waiting',
               'Open vSwitch not configured with an ODL OVSDB controller')


@when_not(configured_state)
def no_ovsdb_manager():
    status_set('blocked', 'Not related to an OpenDayLight OVSDB controller')


@when(configured_state)
def ovsdb_manager():
    status_set('active', 'Open vSwitch configured and ready')


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
                            ('security_group_api', 'neutron'),
                        ],
                    }
                }
            }
        })


@when('controller-api.access.available', installed_state)
def odl_node_registration(controller=None):
    get_charm().odl_node_registration(controller)


@when('controller-api.access.available', installed_state)
def odl_register_macs(controller=None):
    get_charm().odl_register_macs(controller)
