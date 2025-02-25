#!/usr/bin/python3

"""BBRF Client

Usage:
  bbrf (new|use|disable|enable) <program>
  bbrf programs [--show-disabled]
  bbrf program (list [--show-disabled] | [active])
  bbrf domains [--view <view> (-p <program> | --all)]
  bbrf domain (add|remove|update) ( - | <domain>...) [-p <program> -s <source> --show-new]
  bbrf ips [--view <view> --filter-cdns (-p <program> | --all)]
  bbrf ip (add|remove|update) ( - | <ip>...) [-p <program> -s <source> --show-new]
  bbrf scope (in|out) [(--wildcard [--top])] ([-p <program>] | (--all [--show-disabled]))
  bbrf (inscope|outscope) (add|remove) (- | <element>...) [-p <program>]
  bbrf url add ( - | <url>...) [-d <hostname> -s <source> -p <program> --show-new]
  bbrf url remove ( - | <url>...)
  bbrf urls (-d <hostname> | [-p <program>] | --all)  
  bbrf blacklist (add|remove) ( - | <element>...) [-p <program>]
  bbrf agents
  bbrf agent ( list | (register | remove) <agent> | gateway [<url>])
  bbrf run <agent> [-p <program>]
  bbrf show <document>
  bbrf listen
  bbrf alert ( - | <message>) [-s <source>]

Options:
  -h --help     Show this screen.
  -p <program>  Select a program to limit the command to. Not required when the command "use" has been run before.
  -s <source>   Provide an optional source string to store information about the source of the modified data.
  -v --version  Show the program version
  -d <hostname> Explicitly specify the hostname of a URL in case of relative paths
  --show-new    Print new unique values that were added to the database, and didn't already exist
  --all         Specify to get information across all programs. Incompatible with the -p flag
"""

import os
import sys
import json
import re
from bbrf_api import BBRFApi
from urllib.parse import urlparse
from docopt import docopt

CONFIG_FILE = '~/.bbrf/config.json'
# Thanks https://regexr.com/3au3g
REGEX_DOMAIN = re.compile('^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$')
# regex to match IP addresses and CIDR ranges - thanks https://www.regextester.com/93987
REGEX_IP = re.compile('^([0-9]{1,3}\.){3}[0-9]{1,3}(\/([0-9]|[1-2][0-9]|3[0-2]))?$')

class BBRFClient:
    config = {}
    arguments = None
    api = None
    
    def __init__(self, arguments, config=None):
        
        if not str(type(arguments)) == "<class 'docopt.Dict'>":
            self.arguments = docopt(__doc__, argv=arguments, version='BBRF client 0.1b')
        else:
            self.arguments = arguments
            
        if not config:
            self.load_config()
        else:
            self.config = config
        
        if 'username' not in self.config:
            exit('[ERROR] Required configuration was not found: username')
        elif 'password' not in self.config:
            exit('[ERROR] Required configuration was not found: password')
        elif 'couchdb' not in self.config:
            exit('[ERROR] Required configuration was not found: couchdb')
        elif 'slack_token' not in self.config:
            exit('[ERROR] Required configuration was not found: slack_token')
        else:
            self.api = BBRFApi(self.config['couchdb'], self.config['username'], self.config['password'], self.config['slack_token'])

    def new_program(self):
        # First set the program as the active one
        self.use_program(False)
        # and add it to the db
        self.api.create_new_program(self.get_program())

    def list_programs(self, show_disabled):
        return self.api.get_programs(show_disabled)
    
    def list_agents(self):
        return [r['key'] for r in self.api.get_agents()]
    
    def new_agent(self, agent_name):
        self.api.create_new_agent(agent_name)
    
    '''
    Specify a program to be used, and avoid having to type -p <name>
    for every command. The config is stored in CONFIG_FILE.
    '''
    def use_program(self, check_exists=True):
        pro = self.arguments['<program>']
        if check_exists and pro not in self.list_programs(True):
            raise Exception('This program does not exist.')
        self.config['program'] = self.arguments['<program>']
    
    '''
    Check whether a domain matches a scope
    '''
    def matches_scope(self, domain, scope):
        for s in scope:
            # literal match
            if s == domain:
                return True
            # x.example.com matches *.example.com
            if s.startswith('*.') and domain.endswith('.'+s[2:]):
                return True
        return False
    
    '''
    Check whether an IP belongs to a CIDR range
    '''
    def ip_in_cidr(self, ip, cidr):
        from ipaddress import ip_network, ip_address
        return ip_address(ip) in ip_network(cidr)

    '''
    Make abstraction of where the program comes from. It should be either
    specified via the "use" command, or otherwise provided as the -p argument.
    '''
    def get_program(self):
        if self.arguments['-p']:
            return self.arguments['-p']
        elif 'program' in self.config:
            return self.config['program']
        else:
            raise Exception('You need to select a program to execute this action.')
 
    def get_scope(self):   
        if not self.arguments['--all']:
            if self.arguments['in']:
                (scope, _) = self.api.get_program_scope(self.get_program())
            elif self.arguments['out']:
                (_, scope) = self.api.get_program_scope(self.get_program())
        else: # get scope across all programs, making use of _view/scope
            if self.arguments['in']:
                scope = self.api.get_scope('in', 'active' if not self.arguments['--show-disabled'] else 'inactive')
            if self.arguments['out']:
                scope = self.api.get_scope('out', 'active' if not self.arguments['--show-disabled'] else 'inactive')
        
        # filter the scope if --wildcard and/or --top flags are set
        if(self.arguments['--wildcard']):
            r_scope = []
            for s in scope:
                if s.startswith('*.'):
                    r_scope.append(s[2:])
            # only return top-level scope,
            # i.e. 
            if(self.arguments['--top']):
                all_scope = r_scope[:]  # make a copy of the scope before editing it
                for s in all_scope:  # run through each of the wildcard domains
                    for t in r_scope: # and compare to our limited scope copy
                        if s != t and t.endswith(s):
                            r_scope.remove(t)
                        elif s != t and s.endswith(t):
                            if s in r_scope:
                                r_scope.remove(s)

            return r_scope
        else:
            return scope
            
   
    '''
    The BBRF client is responsible for ensuring the added domain is not explicitly outscoped,
    and conforms to the expected format of a domain.
    
    Expected format:
        domains = [
         "a.example.com",
         "b.example.com",
         "c.example.com:1.2.3.4"
         "d.example.com:1.2.3.4,10.0.0.1"
        ]
        
    If a line includes a : delimiter, strip off the ips and add them to the database
    '''
    def add_domains(self, domains):
        (inscope, outscope) = self.api.get_program_scope(self.get_program())
        add_domains = {}
        add_inscope = []
        
        # Keep a copy of the blacklist for reference
        blacklist = self.get_blacklist()
        
        for domain in domains:
            blacklisted_ip = False
            ips = []
            domain = domain.lower()
            
            if ':' in domain:
                print("nope")
                domain, ips = domain.split(':')
                ips = ips.split(',')
                
                for ip in ips:
                    if ip in blacklist:
                        blacklisted_ip = True
                    if not REGEX_IP.match(ip):
                        ips.remove(ip)
                    
            
            # housekeeping
            if domain.endswith('.'):
                domain = domain[:-1]
            
            # not entirely sure this will ever occur, but hey (update: it does occur, as a result of crt.sh)
            # it makes sense to do this here, because it will still check whether it is in scope
            # before extending the existing scope.
            if domain.startswith('*.'):
                domain = domain[2:]
                # if it matches the existing scope definition,
                # add this wildcard to the scope too
                if REGEX_DOMAIN.match(domain) and not self.matches_scope(domain, outscope) and self.matches_scope(domain, inscope):
                    add_inscope.append('*.'+domain)
            
            # Avoid adding blacklisted domains or
            # domains that resolve to blacklisted ips
            if blacklisted_ip or domain in blacklist:
                continue
            # It must match the format of a domain name
            if not REGEX_DOMAIN.match(domain):
                continue
            # It may not be explicitly outscoped
            if self.matches_scope(domain, outscope):
                continue
            # It must match the in scope
            if not self.matches_scope(domain, inscope):
                continue
            add_domains[domain] = ips
        
        # add all new scope at once to drastically reduce runtime of large input
        if len(add_inscope) > 0:
            self.add_inscope(add_inscope)
        
        success, _ = self.api.add_documents('domain', add_domains, self.get_program(), source=self.arguments['-s'])
        
        if self.arguments['--show-new']:
            return ["[NEW] "+x for x in success if x]
    
    '''
    This is now balanced over 100 concurrent threads in order to drastically
    improve the throughput of these requests.
    '''
    def remove_domains(self, domains):
        
        remove = {domain: {'_deleted': True} for domain in domains}
        removed = self.api.update_documents('domain', remove)
        
        if self.arguments['--show-new']:
            return ["[DELETED] "+x for x in removed if x] 

    '''
    Update properties of a domain
    '''
    def update_domains(self, domains):
        update_domains = {}
            
        for domain in domains:
            
            ips = []
            domain = domain.lower()
            
            # split ips if provided
            if ':' in domain:
                domain, ips = domain.split(':')
                ips = ips.split(',')
                
                for ip in ips:
                    if not REGEX_IP.match(ip):
                        ips.remove(ip)
                
            # housekeeping
            if domain.endswith('.'):
                domain = domain[:-1]
                
            update_domains[domain] = {"ips": ips}
        
        updated = self.api.update_documents('domain', {domain: update_domains[domain] for domain in update_domains.keys()})
        
        if self.arguments['--show-new']:
            return [ "[UPDATED] "+x for x in updated if x]
    
    def add_ips(self, ips):
        add_ips = {}
        
        # Keep a copy of the blacklist for reference
        blacklist = self.get_blacklist()
        
        for ip in ips:
            
            blacklisted_domain = False
            domains = []
            
            if ':' in ip:
                ip, domains = ip.split(':')
                domains = domains.split(',')
                
                for domain in domains:
                    if not REGEX_DOMAIN.match(domain):
                        domains.remove(domain)
#                    if domain in blacklist:
#                        blacklisted_domain = True
            
            if blacklisted_domain:
                continue
            if ip in blacklist:
                continue
            if not REGEX_IP.match(ip):
                continue
           
            add_ips[ip] = domains

        success, _ = self.api.add_documents('ip', add_ips, self.get_program(), source=self.arguments['-s'])
        
        if self.arguments['--show-new']:
            return ["[NEW] "+x for x in success if x]
        
    def remove_ips(self, ips):

        remove = {ip: {'_deleted': True} for ip in ips}
        removed = self.api.update_documents('ip', remove)
        
        if self.arguments['--show-new']:
            return ["[DELETED] "+x for x in removed if x] 
            
    '''
    Update properties of an IP
    '''
    def update_ips(self, ips):
        
        update_ips = {}
            
        for ip in ips:
            
            domains = []
            if ':' in ip:
                ip, domains = ip.split(':')
                domains = domains.split(',')
                
            # housekeeping
            updated_domains = []
            for domain in domains:
                if domain.endswith('.'):
                    domain = domain[:-1]
                if REGEX_DOMAIN.match(domain):
                    updated_domains.append(domain)
                
            update_ips[ip] = {"domains": updated_domains}
            
        updated = self.api.update_documents('ip', {ip: update_ips[ip] for ip in update_ips.keys()})
        
        if self.arguments['--show-new']:
            return [ "[UPDATED] "+x for x in updated if x]
    
    '''
    The BBRF client is responsible for ensuring the added urls are added to the appropriate hostname (domain or IP),
    unless a hostname is explicitly provided.
    
    If spaces are found, the input will be split in three parts: path, status code and response size, and the tool will 
    store those as part of the url.
    
    Expected format:
        urls = [
         "http://a.example.com:8080/test",
         "//b.example.com/example",
         "/robots.txt",
         "/page 200 9209",
         "http://hostname.com/page 401 170"
        ]
            
    The database stores urls as individual documents with:
     - identifier (url)
     - status
     - content_length
     - hostname (referencing a domain)
     - program
     
    '''
    def add_urls(self, urls):
        
        (inscope, outscope) = self.api.get_program_scope(self.get_program())
        add_urls = {}
        
        for url in urls:
            parts = url.split(' ')
            url = parts[0]
            
            # To support urls without a schema that aren't relative URLS
            # e.g. '    www.example.com', add a leading protocol 
            if not url.startswith('http://') and not url.startswith('https://') and not url.startswith('/'):
                url = 'http://'+url
                
            # parse properties of the URL
            u = urlparse(url)
            port = u.port
            query = u.query if not u.query == "" else None
            
            # Usually we parse the hostname from the URL,
            # but we don't need to if a hostname is explicitly set
            if not self.arguments['-d']:
                hostname = u.hostname
            else:
                hostname = self.arguments['-d']
                                          
            # It's still possible hostname is empty, e.g. for
            # bbrf url add '/relative' without a -d hostname set;
            # We can't process relative URLS without understanding,
            # so need to skip those for now. Better ideas wecome!
            if not hostname:
                print("Hostname could not be parsed, skipping "+url)
                continue
            
            # If the provided hostname in -d does not match the parsed hostname,
            # we won't add it to avoid polluting the dataset
            if u.hostname and not u.hostname == hostname:
                print("Provided hostname "+hostname+" did not match parsed hostname "+u.hostname+", skipping...")
                continue
                
            # If the provided URL is relative, we need to rewrite the URL
            # with the provided hostname, and we will ALWAYS assume http port 80
            if not u.netloc:
                url = 'http://' + hostname + url
                port = 80
            if url.startswith('//'):
                url = 'http:' + url
                port = 80
            if '?' in url:
                url = url.split('?')[0]
                
            # It must match the format of a domain name or an IP address
            if not REGEX_DOMAIN.match(hostname) and not REGEX_IP.match(hostname):
                print("Illegal hostname:",hostname)
                continue
            # It may not be explicitly outscoped
            if self.matches_scope(hostname, outscope):
                print("skipping outscoped hostname:",hostname)
                continue
            # It must match the in scope
            if not self.matches_scope(hostname, inscope):
                print("skipping not inscope hostname:",hostname)
                continue
            
            if not port:
                if u.scheme == 'http':
                    port = 80
                if u.scheme == 'https':
                    port = 443
            
            if url in add_urls and query not in add_urls[url]['query']:
                add_urls[url]['query'].append(query)
            else:
                if len(parts) == 1: # only a url
                    if not url in add_urls:
                        add_urls[url] = {
                            "hostname": hostname,
                            "port": int(port),
                            "query": [query] if query else []
                        }

                elif len(parts) == 3: # url, status code and content length
                    add_urls[url] = {
                        "hostname": hostname,
                        "port": int(port),
                        "status": int(parts[1]),
                        "content_length": int(parts[2]),
                        "query": [query] if query else []
                    }
        
        success, failed = self.api.add_documents('url', add_urls, self.get_program(), source=self.arguments['-s'])
        
        # assuming the failed updates were the result of duplicates, try bulk updating the url that failed
        updated = self.api.update_documents('url', {url: add_urls[url] for url in failed})
            
        if self.arguments['--show-new']:
            return [ "[UPDATED] "+x for x in updated if x] + ["[NEW] "+x for x in success if x]
        
    '''
    Remove URLs
    '''
    def remove_urls(self, urls):
        
        # parse first comma-seperated value as the url to remove
        # to support `bbrf urls -d example.com | bbrf url remove -`
        
        remove = {url.split(" ")[0]: {'_deleted': True} for url in urls}
        _ = self.api.update_documents('url', remove)
        
    
    def disable_program(self, program):
        if program not in self.list_programs(True):
            raise Exception('The specified program does not exist.')
        self.api.update_document("program", program, {"disabled":True})
        
    def enable_program(self, program):
        if program not in self.list_programs(True):
            raise Exception('The specified program does not exist.')
        self.api.update_document("program", program, {"disabled":False})
        
            
    def add_inscope(self, elements):
        (inscope, outscope) = self.api.get_program_scope(self.get_program())
        
        for e in elements:
            if e not in inscope:
                inscope.append(e)
        
        self.api.update_program_scope(self.get_program(), inscope, outscope)
    
    def remove_inscope(self, elements):
        (inscope, outscope) = self.api.get_program_scope(self.get_program())
        
        for e in elements:
            if e in inscope:
                inscope.remove(e)
                
        self.api.update_program_scope(self.get_program(), inscope, outscope)
        
    def add_outscope(self, elements):
        (inscope, outscope) = self.api.get_program_scope(self.get_program())
        
        for e in elements:
            if e not in outscope:
                outscope.append(e)
        
        self.api.update_program_scope(self.get_program(), inscope, outscope)
    
    def remove_outscope(self, elements):
        (inscope, outscope) = self.api.get_program_scope(self.get_program())
        
        for e in elements:
            if e in outscope:
                outscope.remove(e)
                
        self.api.update_program_scope(self.get_program(), inscope, outscope)
    
    def list_ips(self, list_all = False):
        if list_all:
            return self.api.get_ips_by_program_name()
        return self.api.get_ips_by_program_name(self.get_program())
    
    def list_domains(self, list_all = False):
        if list_all:
            return self.api.get_domains_by_program_name()
        return self.api.get_domains_by_program_name(self.get_program())
    
    def list_urls(self, by, key = False):
        if by == "hostname":
            return self.api.get_urls_by_hostname(key)
        elif by == "program":
            return self.api.get_urls_by_program(key)
        elif by == "all":
            return self.api.get_urls_by_program() # An empty key will return all results
        else:
            return self.api.get_urls_by_program(self.get_program())
    
    def list_documents_view(self, doctype, view, list_all = False):
        if list_all:
            return self.api.get_documents_view(None, doctype, view)
        return self.api.get_documents_view(self.get_program(), doctype, view)
    
    def get_blacklist(self):
        return self.api.get_program_blacklist(self.get_program())
    
    def add_blacklist(self, elements):
        blacklist = self.get_blacklist()
        
        for e in elements:
            if e not in blacklist:
                blacklist.append(e)
        
        self.api.update_program_blacklist(self.get_program(), blacklist)
    
    def remove_blacklist(self, elements):
        blacklist = self.get_blacklist()
        
        for e in elements:
            if e in blacklist:
                blacklist.delete(e)
                
        self.api.update_program_blacklist(self.get_program(), blacklist)
        
    def load_config(self):
        with open(os.path.expanduser(CONFIG_FILE)) as json_file:
            self.config = json.load(json_file)

    def save_config(self):
        with open(os.path.expanduser(CONFIG_FILE), 'w') as outfile:
            json.dump(self.config, outfile)
            
    def listen_for_changes(self):
        self.api.listen_for_changes()

    def run(self):
        
        import pprint
        pp = pprint.PrettyPrinter(indent=4)
        #pp.pprint(self.arguments)
        
        try:
            self.load_config()
        except Exception:
            print('[WARNING] Could not read config file - make sure it exists and is readable')

        if self.arguments['new']:
            self.new_program()

        if self.arguments['use']:
            self.use_program()
            
        if self.arguments['disable']:
            self.disable_program(self.arguments['<program>'])
            
        if self.arguments['enable']:
            self.enable_program(self.arguments['<program>'])

        if self.arguments['programs']:
            return self.list_programs(self.arguments['--show-disabled'])
            
        if self.arguments['program']:
            if self.arguments['list']:
                return self.list_programs(self.arguments['--show-disabled'])
            else:
                return self.get_program()

        if self.arguments['domains']:
            if self.arguments['<view>']:
                return self.list_documents_view("domain", self.arguments['<view>'], self.arguments['--all'])
            else:
                return self.list_domains(self.arguments['--all'])

        if self.arguments['domain']:
            if self.arguments['add']:
                if self.arguments['<domain>']:
                    return self.add_domains(self.arguments['<domain>'])
                elif self.arguments['-']:
                    return self.add_domains(sys.stdin.read().split('\n'))
            if self.arguments['remove']:
                if self.arguments['<domain>']:
                    self.remove_domains(self.arguments['<domain>'])
                elif self.arguments['-']:
                    self.remove_domains(sys.stdin.read().split('\n'))
            if self.arguments['update']:
                if self.arguments['<domain>']:
                    return self.update_domains(self.arguments['<domain>'])
                elif self.arguments['-']:
                    return self.update_domains(sys.stdin.read().split('\n'))

        if self.arguments['ips']:
            if self.arguments['--filter-cdns']:
                ips = self.list_ips(self.arguments['--all'])
                with open(os.path.expanduser('~/.bbrf/cidr-filter.txt')) as f:
                    cidrs = f.read().splitlines()
                filtered = []
                for ip in ips:
                    cdn = False
                    for cidr in cidrs:
                        if self.ip_in_cidr(ip, cidr):
                            cdn = True
                            break
                    if not cdn:
                        filtered.append(ip)
                return filtered
            if self.arguments['<view>']:
                return self.list_documents_view("ip", self.arguments['<view>'], self.arguments['--all'])
            return self.list_ips(self.arguments['--all'])

        if self.arguments['ip']:
            if self.arguments['add']:
                if self.arguments['<ip>']:
                    return self.add_ips(self.arguments['<ip>'])
                elif self.arguments['-']:
                    return self.add_ips(sys.stdin.read().split('\n'))
            if self.arguments['remove']:
                if self.arguments['<ip>']:
                    self.remove_ips(self.arguments['<ip>'])
                elif self.arguments['-']:
                    self.remove_ips(sys.stdin.read().split('\n'))
            if self.arguments['update']:
                if self.arguments['<ip>']:
                    return self.update_ips(self.arguments['<ip>'])
                elif self.arguments['-']:
                    return self.update_ips(sys.stdin.read().split('\n'))

        if self.arguments['inscope']:
            if self.arguments['add']:
                if self.arguments['<element>']:
                    self.add_inscope(self.arguments['<element>'])
                elif self.arguments['-']:
                    self.add_inscope(sys.stdin.read().split('\n'))
            if self.arguments['remove']:
                if self.arguments['<element>']:
                    self.remove_inscope(self.arguments['<element>'])
                elif self.arguments['-']:
                    self.remove_inscope(sys.stdin.read().split('\n'))
                    
        if self.arguments['outscope']:
            if self.arguments['add']:
                if self.arguments['<element>']:
                    self.add_outscope(self.arguments['<element>'])
                elif self.arguments['-']:
                    self.add_outscope(sys.stdin.read().split('\n'))
            if self.arguments['remove']:
                if self.arguments['<element>']:
                    self.remove_outscope(self.arguments['<element>'])
                elif self.arguments['-']:
                    self.remove_outscope(sys.stdin.read().split('\n'))
                    
        if self.arguments['url']:
            if self.arguments['add']:
                if self.arguments['<url>']:
                    return self.add_urls(self.arguments['<url>'])
                if self.arguments['-']:
                    return self.add_urls([u.rstrip() for u in sys.stdin.read().split('\n')])
            if self.arguments['remove']:
                if self.arguments['<url>']:
                    return self.remove_urls(self.arguments['<url>'])
                if self.arguments['-']:
                    return self.remove_urls([u.rstrip() for u in sys.stdin.read().split('\n')])
                    
        if self.arguments['urls']:
            if self.arguments['-d']:
                return self.list_urls("hostname",self.arguments['-d'])
            elif self.arguments['<program>']:
                return self.list_urls("program",self.arguments['<program>'])
            elif self.arguments['--all']:
                return self.list_urls("all")
            else:
                return self.list_urls("self")
            
        if self.arguments['blacklist']:
            if self.arguments['add']:
                if self.arguments['<element>']:
                    self.add_blacklist(self.arguments['<element>'])
                elif self.arguments['-']:
                    self.add_blacklist(sys.stdin.read().split('\n'))
            if self.arguments['remove']:
                if self.arguments['<element>']:
                    self.remove_blacklist(self.arguments['<element>'])
                elif self.arguments['-']:
                    self.remove_blacklist(sys.stdin.read().split('\n'))
        
        if self.arguments['agents']:
            return self.list_agents()
            
        if self.arguments['agent']:
            if self.arguments['list']:
                return self.list_agents()
            if self.arguments['remove']:
                return self.api.remove_document('agent', {'key': self.arguments['<agent>']})
            if self.arguments['register']:
                if self.arguments['<agent>'] not in self.list_agents():
                    return self.new_agent(self.arguments['<agent>'])
                else:
                    return 'This agent is already registered'
            if self.arguments['gateway']:
                if len(self.arguments['<url>']) > 0:
                    return self.api.set_agent_gateway(self.arguments['<url>'][0])
                else:
                    return json.loads(self.api.get_document('agents_api_gateway')).get('url')
        
        if self.arguments['run']:
            return self.api.run_agent(self.arguments['<agent>'], self.get_program())
        
        if self.arguments['show']:
            return self.api.get_document(self.arguments['<document>'])

        if self.arguments['listen']:
            self.listen_for_changes()
            
        if self.arguments['alert']:
            if self.arguments['<message>']:
                self.api.create_alert(self.arguments['<message>'], self.get_program(), self.arguments['-s'])
            elif self.arguments['-']:
                for line in sys.stdin:
                    self.api.create_alert(line, self.get_program(), self.arguments['-s'])
                    
        if self.arguments['scope']:
            return self.get_scope()

        try:
            self.save_config()
        except Exception:
            print('[WARNING] Could not write to config file - make sure it exists and is writable')
            
            
if __name__ == '__main__':
    arguments = docopt(__doc__, version='BBRF client 0.1b')
    bbrf = BBRFClient(arguments)
    result = bbrf.run()
    if result:
        if type(result) is list:
            print("\n".join(result))
        else:
            print(result)