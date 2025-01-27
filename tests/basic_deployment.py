#!/usr/bin/python

import amulet
import os
from neutronclient.v2_0 import client as neutronclient

from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)

from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
)

# Use DEBUG to turn on debug logging
u = OpenStackAmuletUtils(DEBUG)

ODL_QUERY_PATH = '/restconf/operational/opendaylight-inventory:nodes/'
ODL_PROFILES = {
    'helium': {
        'location': 'AMULET_ODL_LOCATION',
        'profile': 'openvswitch-odl'
    },
    'beryllium': {
        'location': 'AMULET_ODL_BE_LOCATION',
        'profile': 'openvswitch-odl-beryllium'
    },
}


class OVSODLBasicDeployment(OpenStackAmuletDeployment):
    """Amulet tests on a basic neutron-openvswtich deployment."""

    def __init__(self, series, openstack=None, source=None, git=False,
                 stable=False, odl_version='helium'):
        """Deploy the entire test environment."""
        super(OVSODLBasicDeployment, self).__init__(series, openstack,
                                                    source, stable)
        self.odl_version = odl_version
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()
        self._initialize_tests()

    def _add_services(self):
        """Add services

           Add the services that we're testing, where openvswitch-odl is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        this_service = {'name': 'openvswitch-odl'}
        other_services = [
            {
                'name': 'nova-compute',
                'constraints': {'mem': '4G'},
            },
            {
                'name': 'neutron-api',
            },
            {
                'name': 'neutron-gateway',
            },
            {
                'name': 'odl-controller',
                'constraints': {'mem': '8G'},
            },
            {
                'name': 'neutron-api-odl',
            },
            {'name': 'mysql'},
            {'name': 'rabbitmq-server'},
            {'name': 'keystone'},
            {'name': 'nova-cloud-controller'},
            {'name': 'glance'},
        ]
        super(OVSODLBasicDeployment, self)._add_services(this_service,
                                                         other_services)

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'neutron-api:neutron-plugin-api-subordinate':
            'neutron-api-odl:neutron-plugin-api-subordinate',
            'nova-compute:neutron-plugin': 'openvswitch-odl:neutron-plugin',
            'openvswitch-odl:ovsdb-manager': 'odl-controller:ovsdb-manager',
            'neutron-api-odl:odl-controller': 'odl-controller:controller-api',
            'keystone:shared-db': 'mysql:shared-db',
            'nova-cloud-controller:shared-db': 'mysql:shared-db',
            'nova-cloud-controller:amqp': 'rabbitmq-server:amqp',
            'nova-cloud-controller:image-service': 'glance:image-service',
            'nova-cloud-controller:identity-service':
            'keystone:identity-service',
            'nova-compute:cloud-compute':
            'nova-cloud-controller:cloud-compute',
            'nova-compute:amqp': 'rabbitmq-server:amqp',
            'nova-compute:image-service': 'glance:image-service',
            'glance:shared-db': 'mysql:shared-db',
            'glance:identity-service': 'keystone:identity-service',
            'glance:amqp': 'rabbitmq-server:amqp',
            'neutron-api:shared-db': 'mysql:shared-db',
            'neutron-api:amqp': 'rabbitmq-server:amqp',
            'neutron-api:neutron-api': 'nova-cloud-controller:neutron-api',
            'neutron-api:identity-service': 'keystone:identity-service',
            'neutron-gateway:amqp': 'rabbitmq-server:amqp',
            'neutron-gateway:neutron-plugin-api':
            'neutron-api:neutron-plugin-api',
            'neutron-gateway:quantum-network-service':
            'nova-cloud-controller:quantum-network-service',
            'neutron-gateway:juju-info': 'openvswitch-odl:container',
        }
        super(OVSODLBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        neutron_api = {
            'neutron-security-groups': False,
        }
        nova_compute = {
            'enable-live-migration': False,
        }
        keystone = {
            'admin-password': 'openstack',
            'admin-token': 'ubuntutesting',
        }
        mysql = {
            'dataset-size': '50%',
        }
        odl_controller = {}
        if os.environ.get(ODL_PROFILES[self.odl_version]['location']):
            odl_controller['install-url'] = \
                os.environ.get(ODL_PROFILES[self.odl_version]['location'])
        if os.environ.get('AMULET_HTTP_PROXY'):
            odl_controller['http-proxy'] = \
                os.environ['AMULET_HTTP_PROXY']
        if os.environ.get('AMULET_HTTP_PROXY'):
            odl_controller['https-proxy'] = \
                os.environ['AMULET_HTTP_PROXY']
        odl_controller['profile'] = \
            ODL_PROFILES[self.odl_version]['profile']
        neutron_gateway = {
            'plugin': 'ovs-odl'
        }
        neutron_api_odl = {
            'overlay-network-type': 'vxlan gre',
        }
        nova_cc = {
            'network-manager': 'Neutron',
        }
        configs = {
            'neutron-api': neutron_api,
            'nova-compute': nova_compute,
            'keystone': keystone,
            'mysql': mysql,
            'odl-controller': odl_controller,
            'neutron-api-odl': neutron_api_odl,
            'neutron-gateway': neutron_gateway,
            'nova-cloud-controller': nova_cc,
        }
        super(OVSODLBasicDeployment, self)._configure_services(configs)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.compute_sentry = self.d.sentry.unit['nova-compute/0']
        self.neutron_api_sentry = self.d.sentry.unit['neutron-api/0']
        self.ovsodl_sentry = self.d.sentry.unit['openvswitch-odl/0']
        self.mysql_sentry = self.d.sentry.unit['mysql/0']
        self.rabbitmq_server_sentry = self.d.sentry.unit['rabbitmq-server/0']
        self.keystone_sentry = self.d.sentry.unit['keystone/0']
        self.glance_sentry = self.d.sentry.unit['glance/0']
        self.nova_cc_sentry = self.d.sentry.unit['nova-cloud-controller/0']
        self.neutron_api_odl_sentry = self.d.sentry.unit['neutron-api-odl/0']
        self.odl_controller_sentry = self.d.sentry.unit['odl-controller/0']
        self.gateway_sentry = self.d.sentry.unit['neutron-gateway/0']
        self.keystone = u.authenticate_keystone_admin(self.keystone_sentry,
                                                      user='admin',
                                                      password='openstack',
                                                      tenant='admin')
        ep = self.keystone.service_catalog.url_for(service_type='identity',
                                                   endpoint_type='publicURL')
        self.neutron = neutronclient.Client(auth_url=ep,
                                            username='admin',
                                            password='openstack',
                                            tenant_name='admin',
                                            region_name='RegionOne')

    def test_services(self):
        """Verify the expected services are running on the corresponding
           service units."""

        commands = {
            self.compute_sentry: ['nova-compute',
                                  'openvswitch-switch'],
            self.gateway_sentry: ['openvswitch-switch',
                                  'neutron-dhcp-agent',
                                  'neutron-l3-agent',
                                  'neutron-metadata-agent',
                                  'neutron-metering-agent',
                                  'neutron-lbaas-agent',
                                  'nova-api-metadata'],
            self.odl_controller_sentry: ['odl-controller'],
        }

        ret = u.validate_services_by_name(commands)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_gateway_bridges(self):
        """Ensure that all bridges are present and configured with the
           ODL controller as their NorthBound controller URL."""
        odl_ip = self.odl_controller_sentry.relation(
            'ovsdb-manager',
            'openvswitch-odl:ovsdb-manager'
        )['private-address']
        # NOTE: 6633 is legacy 6653 is IANA assigned
        if self.odl_version == 'helium':
            controller_url = "tcp:{}:6633".format(odl_ip)
            check_bridges = ['br-int', 'br-ex', 'br-data']
        else:
            controller_url = "tcp:{}:6653".format(odl_ip)
            # NOTE: later ODL releases only manage br-int
            check_bridges = ['br-int']
        cmd = 'ovs-vsctl list-br'
        output, _ = self.gateway_sentry.run(cmd)
        bridges = output.split()
        for bridge in check_bridges:
            if bridge not in bridges:
                amulet.raise_status(
                    amulet.FAIL,
                    msg="Missing bridge {} from gateway unit".format(bridge)
                )
            cmd = 'ovs-vsctl get-controller {}'.format(bridge)
            br_controllers, _ = self.gateway_sentry.run(cmd)
            # Beware of duplicate entries:
            #    https://bugs.opendaylight.org/show_bug.cgi?id=960
            br_controllers = list(set(br_controllers.split('\n')))
            if len(br_controllers) != 1 or br_controllers[0] != controller_url:
                status, _ = self.gateway_sentry.run('ovs-vsctl show')
                amulet.raise_status(
                    amulet.FAIL,
                    msg="Controller configuration on bridge"
                        " {} incorrect: {} != {}\n"
                        "{}".format(bridge,
                                    br_controllers,
                                    controller_url,
                                    status)
                )
