#!/usr/bin/python
#
#  TODO: shoud the following be hardcoded in the config?
#     security_group_id?

import boto3

####################################################################################
# Globals 
####################################################################################

config = {
   'instance_count': 2,               # Number of web instances to deploy
   'instance_type': 't2.micro',
   'ami_id': 'ami-9c0f92fc',          # web-lamp ami, created in the web interface
   'security_groups': ['admin_SG_oregon'],
   'security_group_ids': [],          # TBD, after instance creation
   'availability_zones': ['us-west-2a', 'us-west-2b'],
   'key_pair': 'admin-key-pair-oregon',
   'load_balancer_name': 'web-load-balancer',
   'test': False
}

ec2 = None
instance_ids = []

########################################################################################
# print_header
#
def print_header(header):
  print
  print "*************************************************************"
  print header
  print "*************************************************************"

########################################################################################
# exec_cmd - Execute command and return [stdout, stderr, exitstatus]
#
def exec_cmd(cmd, use_bash = False, fail_on_error = True):

  if use_bash:
    p = subprocess.Popen(cmd, shell=True, executable='/bin/bash', stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
  else:
    p = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  out, err = p.communicate()
  if p.returncode != 0 and fail_on_error:
    print "Command failed:", cmd
    print "    cmd:", cmd
    print "    out:", out
    print "    err:", err
    print "  status:", p.returncode
    sys.exit(1)

  return [out, err, p.returncode]

########################################################################################
# launch_instances - launch the configured number of instances
#
def launch_instances():
  global config
  global instance_ids
  print_header("Launching %s instances" % config['instance_count'])

  if config['test']:
    instance_ids=['i-0e499c52fc6040e0b','i-04044d37e3d00053b']
    response = ec2.describe_instances(
        InstanceIds=instance_ids
    )
    instance = response['Reservations'][0]['Instances'][0]
    config['security_group_ids'].append(instance['SecurityGroups'][0]['GroupId'])
  else:
    for i in range(config['instance_count']):
      num_avail_zones = len(config['availability_zones'])
      print "  Launching instance %s in zone %s" \
            % (i, config['availability_zones'][i % num_avail_zones])

      response = ec2.run_instances(
          ImageId=config['ami_id'], 
          MinCount=1, 
          MaxCount=1, 
          InstanceType=config['instance_type'], 
          KeyName=config['key_pair'], 
          SecurityGroups=config['security_groups'],
          Placement={ 
              'AvailabilityZone': config['availability_zones'][i % num_avail_zones]
          }
      )
 
      instance = response['Instances'][0]
      print "    Instance launched with ID ", instance['InstanceId']
      instance_ids.append(instance['InstanceId'])
      config['security_group_ids'] = [ instance['SecurityGroups'][0]['GroupId'] ]

  print "  Launched instances", ",".join(instance_ids)
  print

########################################################################################
# create_load_balancer_and_register_instances - create load balancer and associate it 
# with instances
#
def create_load_balancer_and_register_instances():
  global lb_dns
  print_header("Creating load balancer")

  client = boto3.client('elb')

  if config['test']:
    response = client.describe_load_balancers(
        LoadBalancerNames = [ config['load_balancer_name'] ]
    )
    lb_dns = response['LoadBalancerDescriptions'][0]['DNSName']
  else:
    response = client.create_load_balancer(
        LoadBalancerName = config['load_balancer_name'],
        AvailabilityZones = config['availability_zones'],
        Listeners = [{
            'Protocol': 'HTTP',
            'LoadBalancerPort': 80,
            'InstanceProtocol': 'HTTP',
            'InstancePort': 80
        }],
        SecurityGroups=config['security_group_ids']
    )
    lb_dns = response['DNSName']

  print "  Load balancer created at", lb_dns

  if not config['test']:
    print_header('Registering instances with load balancer')
    for instance in instance_ids:
      response = client.register_instances_with_load_balancer(
          LoadBalancerName = config['load_balancer_name'],
          Instances=[{
              'InstanceId': instance
          }]
      )
      print '    Instances %s registered with load balancer' % instance

  for instance in instance_ids:
    print_header("Waiting for load balancer to detect healthy instance %s" % instance)
    waiter.wait(
        LoadBalancerName = config['load_balancer_name'],
        Instances=[{
              'InstanceId': instance
        }]
    )
    print '    Instance %s is healthy' % instance

########################################################################################
# wait_for_healthy_instances - Wait for the load balancer to give all registered instances
# a good bill of health.
#
def wait_for_healthy_instances():
  client = boto3.client('elb')
  waiter = client.get_waiter('instance_in_service')
  for instance in instance_ids:
    print_header("Waiting for load balancer to detect healthy instance %s" % instance)
    waiter.wait(
        LoadBalancerName = config['load_balancer_name'],
        Instances=[{
              'InstanceId': instance
        }]
    )
    print '    Instance %s is healthy' % instance

########################################################################################
# validate_load_balancer_dns - Make sure load balancer URL is referencing our web site
#
def validate_load_balancer_dns():
  print_header("Validating %s" % lb_dns)
  cmd = "curl %s" % (lb_dns)

  (out, err, status) = exec_cmd(cmd, use_bash=True)
  if out.find('A Small Hello') == -1:
    print "ERROR: Load Balances DNS %s did not serve the home page" % lb_dns
    sys.exit(1)
  print "   %s is up"

########################################################################################
# main
#
def main():
  global ec2
  ec2 = boto3.client('ec2')

  launch_instances()
  create_load_balancer_and_register_instances()
  wait_for_healthy_instances()
  validate_load_balancer_dns()

if __name__ == "__main__":
  main()

