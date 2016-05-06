import subprocess
from socket import gethostname

from charm.openstack.charm import OpenStackCharmFactory, OpenStackCharm

from charmhelpers.fetch import (
    apt_purge,
)

from charmhelpers.core.hookenv import (
    config,
    log,
    cached,
    status_set,
    unit_private_ip,
)

from charmhelpers.contrib.network.ip import get_address_in_network

import ODL as ODL
import PCIDev as PCIDev


OS_CHARM_NAME = 'openvswitch-odl'


class OpenvswitchODLCharm(OpenStackCharm):

    name = OS_CHARM_NAME
    packages = ['openvswitch-switch']

    def uninstall_packages(self):
        status_set('maintenance', 'Purging packages')
        try:
            apt_purge(self.packages)
            self.remove_state('installed')
        except subprocess.CalledProcessError as e:
            status_set('blocked', 'Apt failure: {}'
                                  ''.format(e))
            raise e

    def _set_manager(self, connection_url):
        '''Configure the OVSDB manager for the switch'''
        subprocess.check_call(['ovs-vsctl', 'set-manager', connection_url])

    @cached
    def _get_ovstbl(self):
        ovstbl = subprocess.check_output(['ovs-vsctl', 'get',
                                          'Open_vSwitch', '.',
                                          '_uuid']).strip()
        return ovstbl

    def _set_config(self, key, value, table='other_config'):
        '''Set key value pairs in the other_config table'''
        subprocess.check_call(
            ['ovs-vsctl', 'set',
             'Open_vSwitch', self._get_ovstbl(),
             '{}:{}={}'.format(table, key, value)]
        )

    def configure_openvswitch(self, odl_ovsdb):
        # NOTE(jamespage): Check connection string as well
        #                  broken/departed seems busted right now
        connection_string = odl_ovsdb.connection_string()
        if connection_string:
            log("Configuring OpenvSwitch with ODL OVSDB controller: %s" %
                connection_string)
            local_ip = get_address_in_network(config('os-data-network'),
                                              unit_private_ip())
            self._set_config('local_ip', local_ip)
            self._set_config('controller-ips', odl_ovsdb.private_address(),
                             table='external_ids')
            self._set_config('host-id', gethostname(),
                             table='external_ids')
            self._set_manager(connection_string)
            self.set_state('{}-openvswitch-configured'.format(self.name))

    def unconfigure_openvswitch(self, odl_ovsdb=None):
        log("Unconfiguring OpenvSwitch")
        subprocess.check_call(['ovs-vsctl', 'del-manager'])
        bridges = subprocess.check_output(['ovs-vsctl',
                                           'list-br']).split()
        for bridge in bridges:
            subprocess.check_call(['ovs-vsctl',
                                   'del-controller', bridge])
        self.remove_state('{}-openvswitch-configured'.format(self.name))

    def odl_node_registration(self, controller=None):
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

    def odl_register_macs(self, controller=None):
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


class OpenvswitchODLCharmFactory(OpenStackCharmFactory):
    """
    Charm Factory
    """

    releases = {
        'icehouse': OpenvswitchODLCharm
    }
    first_release = 'icehouse'
