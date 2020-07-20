from threading import Thread, Lock
import queue
from multiprocessing.managers import BaseManager
import logging
from share.commands import Commands
from libs.distancing import Distancing as CvEngine

logger = logging.getLogger(__name__)

class QueueManager(BaseManager): pass


class ProcessorCore:

    def __init__(self, config):
        self.config = config 
        self._cmd_queue = queue.Queue()
        self._result_queue = queue.Queue()
        self._setup_queues()
        self._engine = CvEngine(self.config)
        self._cmd_thread = Thread( target = self._task_manager, args =(self._cmd_queue, 
                                                                       self._result_queue, self._internal_queue, self) )
       

    def _setup_queues(self):
        QueueManager.register('get_cmd_queue', callable=lambda: self._cmd_queue)
        QueueManager.register('get_result_queue', callable=lambda: self._result_queue)
        self._host = self.config.get_section_dict("CORE")["Host"]
        self._queue_port = int(self.config.get_section_dict("CORE")["QueuePort"])
        auth_key = self.config.get_section_dict("CORE")["QueueAuthKey"]
        self._queue_manager = QueueManager(address=(self._host, self._queue_port), authkey=auth_key.encode('ascii'))
        self._queue_manager.start()
        self._cmd_queue = self._queue_manager.get_cmd_queue()
        self._internal_queue = queue.Queue(1)
        self._result_queue = self._queue_manager.get_result_queue()
        logger.info("Core's queue has been initiated")

       
    def start(self):
        logging.info("Starting processor core")
        self._cmd_thread.start()
        self._serve()
        self._cmd_thread.join()
        logging.info("processor core has been terminated.")
    
    def _task_manager(self, cmd_queue, result_queue, internal_queue, parent):
        tasks = {}
        while True:
            logger.info("Core is listening for commands ... ")
            cmd_code = cmd_queue.get()
            logger.info("command received: " + str(cmd_code))
            if cmd_code == Commands.RESTART:
                # Do everything necessary ... make sure all threads in tasks are stopped 
                if Commands.PROCESS_VIDEO_CFG in tasks.keys():
                    logger.warning("currently processing a video, stopping ...")
                    CvEngine.running_video = False
                    parent._engine.stop_process_video()

                # TODO: Be sure you have done proper action before this so all threads are stopped
                tasks = {}
                try: 
                    internal_queue.put_nowait(cmd_code)
                except queue.Full :
                    result_queue.put("busy")
                continue
            
            elif cmd_code == Commands.PROCESS_VIDEO_CFG:
                if Commands.PROCESS_VIDEO_CFG in tasks.keys():
                    logger.warning("Already processing a video! ...")
                    result_queue.put(False)
                else:
                    try: 
                        internal_queue.put_nowait(cmd_code)
                        tasks[Commands.PROCESS_VIDEO_CFG] = True
                    except queue.Full :
                        result_queue.put("busy")
                continue

            elif cmd_code == Commands.STOP_PROCESS_VIDEO:
                if Commands.PROCESS_VIDEO_CFG in tasks.keys():
                    try: 
                        internal_queue.put_nowait(cmd_code)
                        CvEngine.running_video = False
                        parent._engine.stop_process_video()
                        del tasks[Commands.PROCESS_VIDEO_CFG]
                    except queue.Full :
                        result_queue.put("busy")
                else:
                    logger.warning("no video is being processed")
                    result_queue.put(False)
                continue
            else:
                logger.warning("Invalid core command " + str(cmd_code))
                result_queue.put("invalid_cmd_code")
                continue


    def _serve(self):
        while True:
            cmd_code = self._internal_queue.get() 

            if cmd_code == Commands.RESTART:
                self.config.reload()
                CvEngine.running_video = False
                self._engine.stop_process_video()
                self._engine = CvEngine(self.config)
                self._result_queue.put(True)
                continue
            
            elif cmd_code == Commands.PROCESS_VIDEO_CFG:
                logger.info("started to process video ... ")
                self._result_queue.put(True)
                # Hangs on processing video here untill it is stopped from task manager or video is finished
                self._engine.process_video(self.config.get_section_dict("App").get("VideoPath"))
                # After it is done: 
                CvEngine.running_video = False
                continue
            
            elif cmd_code == Commands.STOP_PROCESS_VIDEO :
                logger.info("processing stopped")
                self._engine.stop_process_video()
                CvEngine.running_video = False
                self._result_queue.put(True)
                continue


