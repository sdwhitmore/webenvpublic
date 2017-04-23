#!/usr/bin/python
#
# This script launches two web instances and then launches a load balancer to distribute
# traffic to those instances.  This load balancer will detect an unhealthy instance and
# will not route traffic to it.
#
# This script does the following
#
#   1) Launches two web-amis (both with LAMP installed), each in a different availability
#      zone
#   2) Creates a classic load balancer that monitors both zones
#   3) Attaches both instances to the classic load balancer
#      Question: do both instances need to be running before they are attached?
#   3) Waits for the instances to be healthy and exits
#
# TODO: 
# *** Priority 1:
#   1) need to validate load balancer after deployment
#      a) DONE: make sure load balancer thinks instances are health
#      b) validate DNS or load balancer
#         This also needs to be in a loop - the curl command did not resolve the 
#         first time
#   2) when bringing up web instances, call script in rc.local to configure them
#   3) Add support for git
#   4) Change % in all strings to format
#   5) Add this script to git repo
# *** Priority 2
#   1) Try to make instances private so that don't have a public DNS or IP
#   2) Try to get auto scaling groups working
# *** Priority 3
#   1) cannot ssh to instances created by this script (Permission denied (publickey))
#      would like to understand how to ssh to instances
#   2) Add code for command line argument processing
#      --test
#      --test-config <json> - has IPS and DNS and populates globals

import json
import subprocess
import sys
import time

test = False

####################################################################################
# Globals - all of these could be command lne arguments or in a database so they
# are not hardcoded anywhere
####################################################################################

config = {
   'instance_count': 2,             # Number of web instances to deploy
   'instance_type': 't2.micro',     
   'ami_id': 'ami-9c0f92fc',        # web-lamp ami, created in the web interface
   'security_group': 'sg-4712bf3c', # admin security group, created in the web interface
   'availability_zones': ['us-west-2a', 'us-west-2b'],
   'key_pair': 'admin-key-pair-oregon',
   'load_balancer_name': 'web-load-balancer'
}

####################################################################################
# Globals - state held by script
####################################################################################

# IDs of web instances that have been launched
instance_ids = []

# DNS of load balancer
lb_dns = None


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
# launch_instances - launch the given number of instances
#
def launch_instances():
  global instance_ids
  print_header("Launching %s instances" % config['instance_count'])

  if test:
    instance_ids = ['i-0b6de7c59ac9b6d80','i-0d920e810c2aae8c4']
  else:
    for i in range(config['instance_count']):
      num_avail_zones = len(config['availability_zones'])
      cmd = (
           'aws ec2 run-instances --image-id {0} --security-group-ids {1} '
           '--count 1 --instance-type {2} --placement AvailabilityZone={3} '
           '--key-name {4} --query \'Instances[0].InstanceId\' --output text').format(
             config['ami_id'], config['security_group'], config['instance_type'],
             config['availability_zones'][i % num_avail_zones], config['key_pair']) 
      print "   - Executing:", cmd
      (out, err, status) = exec_cmd(cmd, use_bash=True)
      instance_ids.append(out.strip())

  print "  Launched instances", ",".join(instance_ids)
  print


########################################################################################
# register_instances - Register the launched web instances with the load balancer
#
def register_instances():
  # TODO: use format??
  print_header("Registering %s with %s" % (",".join(instance_ids), config['load_balancer_name']))

  if not test:
    cmd = (
          'aws elb register-instances-with-load-balancer --load-balancer-name {0} '
          '--instances {1}').format(config['load_balancer_name'], " ".join(instance_ids))
    print "   - Executing:", cmd
    (out, err, status) = exec_cmd(cmd, use_bash=True)

  print "   DONE"



########################################################################################
# create_load_balancer - create load balancer and associate it with instances
#
def create_load_balancer():
  global lb_dns
  print_header("Creating load balancer")

  listeners = "Protocol=HTTP,LoadBalancerPort=80,InstanceProtocol=HTTP,InstancePort=80"

  if test:
    lb_dns = 'web-load-balancer-429110602.us-west-2.elb.amazonaws.com'
  else:
    cmd = (
         'aws elb create-load-balancer --load-balancer-name {0} '
         '--availability-zones {1} --listeners "{2}" --security-groups {3} '
         '--query \'DNSName\' --output text').format(
           config['load_balancer_name'], ' '.join(config['availability_zones']), 
           listeners, config['security_group'])

    print "   - Executing", cmd
    (lb_dns, err, status) = exec_cmd(cmd, use_bash=True)


  print "  Load balancer created at", lb_dns
  register_instances() 

########################################################################################
# wait_for_healthy_instances - Wait for the load balancer to give all registered instances
# a good bill of health.
#
def wait_for_healthy_instances():
  print_header("Waiting for load balancer to detect healthy instances")

  # TODO: configure
  timeout = 300
  cmd = (
         'aws elb describe-instance-health --load-balancer-name {0} '
         '--query \'InstanceStates\'').format(
         config['load_balancer_name'])

  current_time = 0
  inservice = False
  while (current_time < timeout) and (not inservice):
    (out, err, status) = exec_cmd(cmd, use_bash=True)
    instance_states = json.loads(out)

    inservice = True
    for i in instance_states:
      if i['State'] != 'InService':
        print "%s seconds: %s is not in service - retry in 10 seconds" \
              % (current_time, i['InstanceId'])
        time.sleep(10)
        current_time += 10
        inservice = False
        break

      #print i
      #print i['State']

  if inservice:
    print "All instances are up"
    for i in instance_states:
      print "  %s: %s" % (i['InstanceId'], i['State'])

  else:
    print "ERROR: there was a problem with one or more instances"
    sys.exit(1)
  
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
  launch_instances()
  create_load_balancer()
  wait_for_healthy_instances()
  validate_load_balancer_dns()
  return 0


if __name__ == "__main__":
  main()

   
