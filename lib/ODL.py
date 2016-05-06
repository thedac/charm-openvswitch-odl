'''ODL Controller API integration'''
import requests
from jinja2 import Environment, FileSystemLoader
from charmhelpers.core.hookenv import log
from charmhelpers.core.decorators import retry_on_exception


class ODLInteractionFatalError(Exception):
    ''' Generic exception for failures in interaction with ODL '''
    pass


class ODLConfig(requests.Session):

    def __init__(self, username, password, host, port='8181'):
        super(ODLConfig, self).__init__()
        self.mount("http://", requests.adapters.HTTPAdapter(max_retries=5))
        self.base_url = 'http://{}:{}'.format(host, port)
        self.auth = (username, password)
        self.proxies = {}
        self.timeout = 10
        self.conf_url = self.base_url + '/restconf/config'
        self.oper_url = self.base_url + '/restconf/operational'
        self.netmap_url = self.conf_url + '/neutron-device-map:neutron_net_map'
        self.node_query_url = self.oper_url + '/opendaylight-inventory:nodes/'
        yang_mod_path = ('/opendaylight-inventory:nodes/node/'
                         'controller-config/yang-ext:mount/config:modules')
        self.node_mount_url = self.conf_url + yang_mod_path

    @retry_on_exception(5, base_delay=30,
                        exc_type=requests.exceptions.ConnectionError)
    def contact_odl(self, request_type, url, headers=None, data=None,
                    whitelist_rcs=None, retry_rcs=None):
        response = self.request(request_type, url, data=data, headers=headers)
        ok_codes = [requests.codes.ok, requests.codes.no_content]
        retry_codes = [requests.codes.service_unavailable]
        if whitelist_rcs:
            ok_codes.extend(whitelist_rcs)
        if retry_rcs:
            retry_codes.extend(retry_rcs)
        if response.status_code not in ok_codes:
            if response.status_code in retry_codes:
                msg = "Recieved {} from ODL on {}".format(response.status_code,
                                                          url)
                raise requests.exceptions.ConnectionError(msg)
            else:
                msg = "Contact failed status_code={}, {}".format(
                    response.status_code, url)
                raise ODLInteractionFatalError(msg)
        return response

    def get_networks(self):
        log('Querying macs registered with odl')
        # No netmap may have been registered yet, so 404 is ok
        odl_req = self.contact_odl(
            'GET', self.netmap_url, whitelist_rcs=[requests.codes.not_found])
        if not odl_req:
            log('neutron_net_map not found in ODL')
            return {}
        odl_json = odl_req.json()
        if odl_json.get('neutron_net_map'):
            log('neutron_net_map returned by ODL')
            return odl_json['neutron_net_map']
        else:
            log('neutron_net_map NOT returned by ODL')
            return {}

    def delete_net_device_entry(self, net, device_name):
        obj_url = self.netmap_url + \
            'physicalNetwork/{}/device/{}'.format(net, device_name)
        self.contact_odl('DELETE', obj_url)

    def get_odl_registered_nodes(self):
        log('Querying nodes registered with odl')
        odl_req = self.contact_odl('GET', self.node_query_url)
        odl_json = odl_req.json()
        odl_node_ids = []
        if odl_json.get('nodes'):
            odl_nodes = odl_json['nodes'].get('node', [])
            odl_node_ids = [entry['id'] for entry in odl_nodes]
        log('Following nodes are registered: ' + ' '.join(odl_node_ids))
        return odl_node_ids

    def odl_register_node(self, device_name, ip):
        log('Registering node {} ({}) with ODL'.format(device_name, ip))
        payload = self.render_node_xml(device_name, ip)
        headers = {'Content-Type': 'application/xml'}
        # Strictly a client should not retry on recipt of a bad_request (400)
        # but ODL return 400s while it is initialising
        self.contact_odl(
            'POST', self.node_mount_url, headers=headers, data=payload,
            retry_rcs=[requests.codes.bad_request])

    def odl_register_macs(self, device_name, network, interface, mac,
                          device_type='vhostuser'):
        log('Registering {} and {} on {}'.format(network, interface, mac))
        payload = self.render_mac_xml(device_name, network, interface, mac,
                                      device_type)
        headers = {'Content-Type': 'application/json'}
        self.contact_odl(
            'POST', self.netmap_url, headers=headers, data=payload)

    def get_macs_networks(self, mac):
        registered_networks = self.get_networks()
        nets = []
        phy_nets = registered_networks.get('physicalNetwork')
        if phy_nets:
            for network in phy_nets:
                for device in network.get('device', []):
                    for interface in device['interface']:
                        if interface['macAddress'] == mac:
                            nets.append(network['name'])
        return nets

    def is_device_registered(self, device_name):
        return device_name in self.get_odl_registered_nodes()

    def is_net_device_registered(self, net_name, device_name, interface_name,
                                 mac, device_type='vhostuser'):
        networks = self.get_networks()
        phy_nets = networks.get('physicalNetwork')
        if phy_nets:
            for net in phy_nets:
                if net_name == net['name']:
                    for dev in net.get('device', []):
                        if device_name == dev['device-name'] \
                                and dev['device-type'] == device_type:
                            for interface in dev['interface']:
                                if (interface_name ==
                                        interface['interface-name'] and
                                        mac == interface['macAddress']):
                                    return True
        return False

    def render_node_xml(self, device_name, ip, user='admin', password='admin'):
        env = Environment(loader=FileSystemLoader('templates'))
        template = env.get_template('odl_registration')
        node_xml = template.render(
            vpp_host=device_name,
            vpp_ip=ip,
            vpp_username=user,
            vpp_password=password,
        )
        return node_xml

    def render_mac_xml(self, device_name, network, interface, mac,
                       device_type='vhostuser'):
        env = Environment(loader=FileSystemLoader('templates'))
        template = env.get_template('mac_registration')
        mac_xml = template.render(
            vpp_host=device_name,
            network=network,
            interface=interface,
            mac=mac,
            device_type=device_type,
        )
        return mac_xml
