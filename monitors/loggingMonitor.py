
import sys
sys.path.append('../')
from monitor import AbstractMonitor
import logging

class LoggingMonitor(AbstractMonitor):
    
    def __init__(self):
        self.logger = logging.getLogger('OutputMonitorLogger')
        self.hdlr = logging.FileHandler('./log/monitor.log')
        self.formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        self.hdlr.setFormatter(self.formatter)
        self.logger.addHandler(self.hdlr)
        self.logger.setLevel(logging.DEBUG)
        
    def __taskset_event__(self, taskset):
        pass

    def __taskset_start__(self, taskset):
        pass

    def __taskset_finish__(self, taskset):
        for task in taskset:
            self.logger.info("task: {}".format(task.id))
            for job in task.jobs:
                self.logger.info("{} {}".format(job.start_date, job.end_date))

    def __taskset_stop__(self, taskset):
        pass




