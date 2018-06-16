"""Module for asyncron distribution of task-sets

This modules provides a class for the distribution of task-sets to one or
multiple target plattforms. The connection to a target plattform is handled by a
session.

"""
import threading
import time
import logging
import errno
import importlib
import copy
from queue import Empty, Queue, Full
from subprocess import Popen, PIPE
from monitor import AbstractMonitor
from session import AbstractSession
from machine import Machine

import os
import sys
sys.path.append('../')
from taskgen.taskset import TaskSet


"""
def clean_id(path, id, logger):
    Popen(['screen', '-wipe'], stdout=PIPE, stderr=PIPE)
    pids = Popen(['{}/grep_screen.sh'.format(path), str(id)], stdout=PIPE, stderr=PIPE).communicate()[0].split()
    c = 0
    for p in pids:
        Popen(['screen', '-X','-S', str(p,'utf-8'), 'kill'])
        Popen(['sudo', 'ip', 'link', 'delete', 'tap{}'.format(id)], stdout=PIPE, stderr=PIPE)
        c+=1
    logger.info("clean_id():for id {} removed {} screen(s)".format(id, c))
"""
class Distributor:
    """Class for controll over host sessions and asycronous distribution of tasksets"""
    
    def __init__(self, max_machine = 1):
        self.max_allowed_machines = 42 #this value is hardcoded and dependant on the amount of defined entrys in the dhcpd.conf
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        
        self.logger = logging.getLogger('Distributor')
        if not len(self.logger.handlers):
            self.hdlr = logging.FileHandler('{}/log/distributor.log'.format(self.script_dir))
            self.formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
            self.hdlr.setFormatter(self.formatter)
            self.logger.addHandler(self.hdlr)
            self.logger.setLevel(logging.DEBUG)

        #self._kill_log = '/tmp/taskgen_qemusession_ip_kill.log'
        #with open(self._kill_log, 'w') as swipe_log:
        #    swipe_log.write("")

        #open(self._kill_log, 'a').close()
        
        self._max_machine = max_machine
        self._machines = []

        self._port = 3001
        self._session_class = getattr(importlib.import_module("sessions.genode"), "QemuSession")
        
        

        self._taskset_list_lock = threading.Lock()
        self._tasksets = []
        
        self._bridge = "br0"
        self._cleaner = None
        self.id_to_machine={}
        self.machinestate={}
        for i in range(self.max_allowed_machines):
            index=i+1
            self.machinestate[index]=0
        self._qemu_killer=threading.Thread(target=Distributor._kill_log_killer, args=(self,))
        self._qemu_killer.start()
        self.logger.info("=====================================================")
        self.logger.info("Distributor started")
        self.logger.info("=====================================================")


    def _kill_log_killer(self):
        self.logger.info("kill_log_killer: spawned kill log killer")
        kill_ip = None
        while True: 
            self.logger.debug("kill_log_killer: Entering kill function")
            self.logger.info("kill_log_killer: id_to_machine: {}".format(self.id_to_machine))
            self.logger.debug("kill_log_killer: machinestates: {}".format(self.machinestate))
            self.logger.debug("kill_log_killer: machines: {}".format(self._machines))
            self.logger.info("kill_log_killer: [(processing/-ed, of total)]: {}".format([(tset.already_used,tset.total_it_length) for tset in self._tasksets]))
            time.sleep(5)
            #in_str = []
            #with open(self._kill_log, 'r+') as f:
            #    in_str = f.read().split("\n")
            #    f.seek(0)
            #    f.write("")
            #    f.truncate()
            #self.logger.debug("kill_log_killer: file content: {}".format(in_str))
            #for line in in_str:
            #    if line != '':
            #        kill_ip = line.split(".")
            #        self.logger.debug("kill_log_killer: found {}".format(kill_ip))
            #        if(kill_ip is not None):
            #            try:
            #                kill_id=int(kill_ip[-1])
            #                self.logger.info("kill_log_killer: Trying to kill id: {} ".format(kill_id))
            #                Popen(['screen', '-wipe'], stdout=PIPE, stderr=PIPE)
            #                pids = Popen(['{}/grep_screen.sh'.format(self.script_dir), str(kill_id)], stdout=PIPE, stderr=PIPE).communicate()[0].split()
            #                c = 0
            #                for p in pids:
            #                    Popen(['screen', '-X','-S', str(p,'utf-8'), 'kill'])
            #                    Popen(['sudo', 'ip', 'link', 'delete', 'tap{}'.format(kill_id)], stdout=PIPE, stderr=PIPE)
            #                    c+=1
            #                self.logger.info("kill_log_killer():for id {} removed {} screen(s)".format(kill_id, c))
            #                self.logger.debug("kill_log_killer: killed host with ip: {} and id: {}".format(kill_ip, kill_id))                    
            #                del self.id_to_pid[kill_id]
            #            except KeyError as e:
            #                self.logger.error("kill_log_killer: the qemu with id {} was not up".format(str(int(kill_ip[-1]))))
            #            kill_ip = None
            #            kill_id = -1
            #            
            #in_str =[]
            #Continue searching


    def get_distributor_state(self):    
        #function to check if the distributor is already working
        #under the assumption that the distributor is working as soon as there are tasksets to work on

        ret = False
        
        with self._taskset_list_lock:
            
            if self._tasksets:
                
                ret = True 
       
        return ret

    def get_max_machine_value(self):
        """Returns the current max_machine value."""
        return self._max_machine 



    def set_max_machine_value(self, new_value):
        """Changes the _max_machine value. 
        :param new_value int: positive non zero value
        :raises ValueError: new_value is not a natural number
        """
        
        if(isinstance(new_value, int) and 0 < new_value):
            if new_value > self.max_allowed_machines:
                self.logger.debug("the new value in set_max_machine_value was {}, thus bigger than the max_allowed_machines of {} the _max_machine value was set to the max_allowed_machines value".format(new_value,self.max_allowed_machines))
                self._max_machine = self.max_allowed_machines
            else:
                self.logger.info("Adjusted the max_machine value from {} to {}".format(self._max_machine, new_value))
                self._max_machine = new_value
            self._refresh_machines()
        else:
            raise ValueError("The new max_machine value is not an integer greater than zero.")

    def _refresh_machines(self):
        #Adjusts the amount of running starter threads to the current max_machine value.
        #first checking if 
        working = False
        with self._taskset_list_lock:
            if self._tasksets:
                working = True
            
            if working:
                if not self._machines:
                    for c in range(0, self._max_machine):
                        new_id = -1
                        found = False
                        for k, v in self.machinestate.items():
                            if not found:
                                if v == 0:
                                    found = True
                                    new_id = k
                                    self.machinestate[k] = 1
                                    break
                        if new_id != -1:
                            m_running = threading.Event()
                            machine = Machine(new_id, self._taskset_list_lock, self._tasksets, self._port, self._session_class, self._bridge, m_running, self.id_to_machine)
                            machine.start()
                            self.id_to_machine[new_id] = machine
                            self._machines.append((machine, m_running, new_id))
                    self._cleaner = threading.Thread(target = Distributor._clean_machines, args = (self,))#cleans machines from _machines which terminated
                    self._cleaner.start()
                    self.logger.info("started {} machines".format(len(self._machines)))
                
                else:
                    l = self._max_machine - len(self._machines)
                    if l > 0:
                        for c in range(0,l):
                            new_id = -1
                            found = False
                            for k, v in self.machinestate.items():
                                if not found:
                                    if v == 0:
                                        found = True
                                        new_id = k
                                        self.machinestate[k] = 1
                                        break
                            if new_id != -1:
                                m_running = threading.Event()
                                machine = Machine(new_id, self._taskset_list_lock, self._tasksets, self._port, self._session_class, self._bridge, m_running, self.id_to_machine)
                                machine.start()
                                self.id_to_machine[new_id] = machine
                                self._machines.append((machine,m_running, new_id))
                        self.logger.info("started {} additional machines".format(abs(l)))
                    elif l < 0:
                        for k in range(0,abs(l)):
                            triple = self._machines.pop()
                            machine=triple[0]
                            machine.close()
                            self.machinestate[triple[2]]=0
                        self.logger.info("closed {} machines".format(abs(l)))
            else:
                self.logger.debug("no machines currently running")

    def add_job(self, taskset, monitor = None, offset = 0, *session_params):
        #   Adds a taskset to the queue and calls _refresh_machines()
        #   :param taskset taskgen.taskset.TaskSet: a taskset for the distribution
        #   :param monitor distributor_service.monitor.AbstractMonitor: a monitor to handle the resulting data
        #   :param offset  number of tasksets that should be discarded from the head of the generator
        #   :param session_params: optional parameters which are passed to the
        #   `start` method of the actual session. Pay attention: Theses parameters
        #   must be implemented by the session class. A good example is the
        #   `taskgen.sessions.genode.GenodeSession`, which implements a parameter
        #   for optional admission control configuration.  
        
        if taskset is None or not isinstance(taskset, TaskSet):
            raise TypeError("taskset must be of type TaskSet.")

        if monitor is not None:
            if not isinstance(monitor, AbstractMonitor):
                raise TypeError("monitor must be of type AbstractMonitor")

        # wrap tasksets into an threadsafe iterator
        generator = taskset.variants()
        try:
            for i in range(offset):
                discard = generator.__next__()
            with self._taskset_list_lock:
                self._tasksets.append(_TaskSetQueue(generator, monitor, offset, len(list(taskset.variants())), session_params))#TODO will ich hier immer variants aufrufen?
            self.logger.info("a new job was added, offset was {}".format(offset))
            self._refresh_machines()
        except StopIteration:
            self.logger.error("offset was bigger than taskset size, no job was added")
            

    def kill_all_machines(self):
        #hard kill, callable from outside
        self.logger.info("\n====############=====\nKilling machines")
        for m in self._machines:
            m[1].set()
        self.logger.info("\nAll machines shuting down.\n====############=====")

    def _clean_machines(self):
        #cleans up machines which are not running
        self.logger.info("cleaner: started, will clean up not running machines")
        dead = []
        while self._machines:
            time.sleep(10)
            self.logger.debug("cleaner: id_to_machine: {}".format(self.id_to_machine))
            self.logger.debug("cleaner: machinestates: {}".format(self.machinestate))
            self.logger.info("cleaner: looking for inactive machines")
            for m in self._machines:
                if m[1].is_set():
                    self.logger.debug("cleaner: found inactive machine with id -{}-".format(m[2]))
                    dead.append(m)
            for d in dead:
                self.machinestate[d[2]]=0
                self.logger.debug("cleaner: removing machine with id -{}-".format(d[2]))
                self._machines.remove(d)
            dead = []
        self.logger.info("cleaner: stopped because there are no machines left")

class _TaskSetQueue():
    """Takes an iterator/generator and makes it thread-safe by
    serializing call to the `next` method of given iterator/generator.
    """
    def __init__(self, iterator, monitor, start_from, it_length, *session_params):
        self.it = iterator #the tasksets
        self.total_it_length = it_length
        self.already_used = start_from
        self.lock = threading.Lock()
        self.queue = Queue(maxsize=1000)
        self.in_progress = []
        self.processed = 0
        self.logger = logging.getLogger("Distributor")
        self.monitor = monitor
        self.session_params = session_params

        
    def get(self):
        # return a regular taskset
        with self.lock:
            taskset = None
            if not self.queue.empty():
                taskset = self.queue.get_nowait()
                
            # take a new one from the iterator
            if taskset is None:
                taskset = copy.deepcopy(self.it.__next__())

            # keep track of current processed tasksets
            self.in_progress.append(taskset)
            self.already_used +=1
            return taskset
            
    def empty(self):
        with self.lock:
            # in progress?
            #if len(self.in_progress) > 0:
            #    return False
            # in queue?
            if not self.queue.empty():
                return False
            # in iterator?
            try:
                self.queue.put(copy.deepcopy(self.it.__next__()))
                return False
            except StopIteration:
                return True

    def done(self, taskset):
        """Call this method, if a task-set is finally processed.

        This mechanism keeps references of currenctly processed task-sets.

        """
        with self.lock:
            self.in_progress.remove(taskset)
            self.processed += 1
            self.logger.info("{} taskset variant(s) processed".format(self.processed))
        
    def put(self, taskset):
        """Call this method, if a task-set processing is canceled.

        This mechanism keeps references of currenctly processed task-sets.

        """
        with self.lock:
            try:
                self.in_progress.remove(taskset)
                for task in taskset:
                    task.jobs = []
                self.queue.put_nowait(taskset)
                self.already_used -= 1
            except Full:
                # We don't care about the missed taskset. Actually, there is a bigger
                # problem:
                self.logger.critical("The Push-Back Queue of tasksets is full. This is a"
                    + "indicator, that the underlying session is buggy"
                    + " and is always canceling currently processed tasksets.")
