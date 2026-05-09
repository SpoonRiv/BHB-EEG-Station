#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: SSVEP 刺激实验脚本（PsychoPy 刺激 + LSL 拉流 + FBCCA 识别）

修改日志:
- 2026-05-09: 1.0.0 创建文件

作者: Fengye
版本: 1.0.0
"""

from __future__ import absolute_import, division

import asyncio
import multiprocessing
import os  # handy system and path functions
import socket
import time
import warnings

import numpy as np
import pandas as pd
import pylsl
from numpy import pi, sin
from pylsl import StreamInlet, StreamInfo, StreamOutlet
from scipy.signal import cheb1ord, cheby1, resample

from core.signal import fbcca

warnings.filterwarnings("ignore")

try:
    from psychopy import core, data, gui, logging, visual
    from psychopy.constants import FINISHED, NOT_STARTED, STARTED
    from psychopy.hardware import keyboard
except ModuleNotFoundError:
    core = None
    data = None
    gui = None
    logging = None
    visual = None
    FINISHED = None
    NOT_STARTED = None
    STARTED = None
    keyboard = None


'''
V0.02 检测阻抗
V0.03 阻抗检测后切换回采集数据
'''

'''
更改人:贾文骥
时间:2025年3月10日
V1 为了测试trigger功能是否为上位机问题,将使用线程启动脑电数据接收程序
修改为独立运行脑电接收数据,为了传递trigger开始信息,使用socket进行程序间通信.
'''


class client:
    def __init__(self, port):
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.connect(('127.0.0.1', port))

    def send_trigger(self, command):
        byte_command = command.encode('utf-8')
        self.client_socket.sendall(byte_command)
        print(byte_command)

    def close_client(self):
        self.client_socket.close()


def received_data(queue, save_path):
    while True:
        if hasattr(pylsl, "resolve_stream"):
            streams = pylsl.resolve_stream("type", "EEG")
        else:
            streams = pylsl.resolve_byprop("type", "EEG", timeout=1.0)
        inlet = StreamInlet(streams[0], max_chunklen=10)
        eeg_data = []
        word = queue.get()
        print("time: {}, 开始记录数据: {}".format(time.time(), word))
        if word.startswith("start"):
            print(1)
            while True:
                sample, timestamps = inlet.pull_sample()
                eeg_data.append(sample)
                if not queue.empty():
                    end_word = queue.get()
                    if end_word == "end":
                        break
            eeg_data = np.array(eeg_data)
            print("time: {}, 存储数据: {}, shape: {} ".format(time.time(), word, eeg_data.shape))
            pd.DataFrame(eeg_data).to_csv(os.path.join(save_path, "{}.csv".format(word)))
        elif word == "del":
            print("存储脑电程序退出")
            break


def quit_function():
    time.sleep(1)
    if core is not None:
        core.quit()


def decorator(func):
    def wrapper(*args, **kwargs):
        try:
            res = func(*args, **kwargs)
            return res
        except Exception as e:
            print("执行函数：{}，出现异常：{}".format(func.__name__, e))
    return wrapper


def start_ssvep_experiment(save_dir_base="D:\\ssvep\\eeg_data"):
    """
    被 main.py 调用的入口函数
    """
    if gui is None or visual is None or core is None:
        raise RuntimeError("SSVEP 依赖 psychopy 未安装：请先在当前环境安装 psychopy 后再启动该模式")
    import os
    import multiprocessing
    import time
    
    # 自动生成基于日期的路径
    date_str = time.strftime("%Y%m%d")
    save_path = os.path.join(save_dir_base, date_str)
    if not os.path.exists(save_path):
        os.makedirs(save_path, exist_ok=True)
    queue = multiprocessing.Queue()
    port=8888
    iftcp=False
    text=True
    if iftcp:
        trigger_client=client(port)
    process2 = multiprocessing.Process(target=received_data, args=(queue, save_path))
    process2.daemon = True
    process2.start()
    # 开启记录数据程序
    time.sleep(10)

    # time of stimulation
    trial_dura = 5
    stim_t = 4
    if text:
        next_target=0
        k=0
    _thisDir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(_thisDir)
    # ser = serial.Serial('COM17', 9600, timeout=10)
    psychopyVersion = '3.2.4'
    expName = 'tello_control'  # from the Builder filename that created this script
    expInfo = {'participant': '', 'session': '001'}
    dlg = gui.DlgFromDict(dictionary=expInfo, sortKeys=False, title=expName)
    if dlg.OK == False:
        quit_function()  # user pressed cancel
    expInfo['date'] = data.getDateStr()  # add a simple timestamp
    expInfo['expName'] = expName

    # Data file name stem = absolute path + name; later add .psyexp, .csv, .log, etc
    filename = _thisDir + os.sep + u'data/%s_%s_%s' % (expInfo['participant'], expName, expInfo['date'])

    endExpNow = False  # flag for 'escape' or other condition => quit the exp
    frameTolerance = 0.001  # how close to onset before 'same' frame

    # Setup the Window
    win = visual.Window(
        size=[1920, 1080], fullscr=True, screen=1,
        winType='pyglet', allowGUI=False, allowStencil=False,
        monitor='testMonitor', color=[-1.000, -1.000, -1.000], colorSpace='rgb',
        blendMode='avg', useFBO=True,
        units='height')
    # store frame rate of monitor if we can measure it
    expInfo['frameRate'] = win.getActualFrameRate()
    if expInfo['frameRate'] != None:
        frameDur = 1.0 / round(expInfo['frameRate'])
        print("frameRate", round(expInfo['frameRate']))
    else:
        frameDur = 1.0 / 60.0  # could not measure, so guess

    # create a default keyboard (e.g. to check for escape)
    defaultKeyboard = keyboard.Keyboard()

    # Initialize components for Routine "instr"
    instrClock = core.Clock()
    text = visual.TextStim(win=win, name='text',
                           text='脑机接口\n\n无人机控制\n\n按"空格"继续\n\n可随时按"ESC"退出',
                           font='Arial',
                           units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                           color='white', colorSpace='rgb', opacity=1,
                           languageStyle='LTR',
                           depth=0.0)
    i0=1
    key_resp = keyboard.Keyboard()
    # instr Begin Experiment
    Freq = np.array([8.00, 9.00, 10.00, 11.00, 12.00, 13.00, 14.00, 15.00])
    Phas = np.array([0, 0.15, 0.3, 0.45, 0.60, 0.75, 0.9, 0])

    varpy = [600, 90]

    screen_long = 1920
    screen_width = 1080
    x0 = screen_long * 0 / 4 - screen_long / 2
    x1 = screen_long * 1 / 4 - screen_long / 2
    x2 = screen_long * 2 / 4 - screen_long / 2
    x3 = screen_long * 3 / 4 - screen_long / 2
    x4 = screen_long * 4 / 4 - screen_long / 2

    y0 = screen_width * 0 / 4 - screen_width / 2
    y1 = screen_width * 1 / 4 - screen_width / 2
    y2 = screen_width * 2 / 4 - screen_width / 2
    y3 = screen_width * 3 / 4 - screen_width / 2
    y4 = screen_width * 4 / 4 - screen_width / 2

    mylocation = [
        [(x0 + x1) / 2, (y3 + y4) / 2],  ##上升
        [x2, (y3 + y4) / 2],  ##前进
        [(x0 + x1) / 2, (y0 + y1) / 2],  ##起飞
        [(x0 + x1) / 2, y2],  ##左转
        [(x3 + x4) / 2, y2],  ##右转
        [(x3 + x4) / 2, (y0 + y1) / 2],  ##降落
        [x2, (y0 + y1) / 2],  ##后退
        [(x3 + x4) / 2, (y3 + y4) / 2]  ##下降
    ]

    size_w = 300
    size_h = 300
    order_lst = ['\n+\n8Hz', '\n+\n9Hz', '\n+\n10Hz', '\n+\n11Hz', '\n+\n12Hz', '\n+\n13Hz', '\n+\n14Hz', '\n+\n15Hz']
    # Initialize components for Routine "cue"
    cueClock = core.Clock()
    command_0 = visual.TextStim(win=win, name='text',
                                text='脑机接口\n\n无人机控制\n\n按"空格"继续\n\n可随时按"ESC"退出',
                                font='Arial',
                                units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                                color='white', colorSpace='rgb', opacity=1,
                                languageStyle='LTR',
                                depth=0.0)
    polygon_0 = visual.Rect(
        win=win, name='polygon_0', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=0.0, interpolate=True)
    order_0 = visual.TextStim(win=win, name='text',
                              text=order_lst[0],
                              font='Arial',
                              units='pix', pos=(0, 0), height=100, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=0.0)

    polygon_1 = visual.Rect(
        win=win, name='polygon_1', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-1.0, interpolate=True)
    order_1 = visual.TextStim(win=win, name='text',
                              text=order_lst[1],
                              font='Arial',
                              units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=-1.0)

    polygon_2 = visual.Rect(
        win=win, name='polygon_2', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-2.0, interpolate=True)
    order_2 = visual.TextStim(win=win, name='text',
                              text=order_lst[2],
                              font='Arial',
                              units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=-2.0)

    polygon_3 = visual.Rect(
        win=win, name='polygon_3', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-3.0, interpolate=True)
    order_3 = visual.TextStim(win=win, name='text',
                              text=order_lst[3],
                              font='Arial',
                              units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=-3.0)

    polygon_4 = visual.Rect(
        win=win, name='polygon_5', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-5.0, interpolate=True)
    order_4 = visual.TextStim(win=win, name='text',
                              text=order_lst[4],
                              font='Arial',
                              units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=-5.0)

    polygon_5 = visual.Rect(
        win=win, name='polygon_6', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-6.0, interpolate=True)
    order_5 = visual.TextStim(win=win, name='text',
                              text=order_lst[5],
                              font='Arial',
                              units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=-6.0)

    polygon_6 = visual.Rect(
        win=win, name='polygon_7', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-7.0, interpolate=True)
    order_6 = visual.TextStim(win=win, name='text',
                              text=order_lst[6],
                              font='Arial',
                              units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=-7.0)

    polygon_7 = visual.Rect(
        win=win, name='polygon_8', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-8.0, interpolate=True)
    order_7 = visual.TextStim(win=win, name='text',
                              text=order_lst[7],
                              font='Arial',
                              units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                              color='white', colorSpace='rgb', opacity=1,
                              languageStyle='LTR',
                              depth=-8.0)
    # ------------
    loop_id = -1

    # Initialize components for Routine "trial"
    trialClock = core.Clock()

    polygon_trial_0 = visual.Rect(
        win=win, name='polygon_trial_0', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=1.0, fillColorSpace='rgb',
        opacity=1, depth=0.0, interpolate=True)
    font='SimHei'
    h=60
    order_trial_0 = visual.TextStim(win=win, name='text',
                                    text=order_lst[0],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=0.0)

    polygon_trial_1 = visual.Rect(
        win=win, name='polygon_trial_1', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=1.0, fillColorSpace='rgb',
        opacity=1, depth=-1.0, interpolate=True)
    order_trial_1 = visual.TextStim(win=win, name='text',
                                    text=order_lst[1],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=-1.0)

    polygon_trial_2 = visual.Rect(
        win=win, name='polygon_trial_2', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=1.0, fillColorSpace='rgb',
        opacity=1, depth=-2.0, interpolate=True)
    order_trial_2 = visual.TextStim(win=win, name='text',
                                    text=order_lst[2],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=-2.0)

    polygon_trial_3 = visual.Rect(
        win=win, name='polygon_trial_3', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=1.0, fillColorSpace='rgb',
        opacity=1, depth=-3.0, interpolate=True)
    order_trial_3 = visual.TextStim(win=win, name='text',
                                    text=order_lst[3],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=-3.0)

    polygon_trial_4 = visual.Rect(
        win=win, name='polygon_trial_4', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=[1, 1, 1], fillColorSpace='rgb',
        opacity=1, depth=-5.0, interpolate=True)
    order_trial_4 = visual.TextStim(win=win, name='text',
                                    text=order_lst[4],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=-5.0)

    polygon_trial_5 = visual.Rect(
        win=win, name='polygon_trial_5', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=1.0, fillColorSpace='rgb',
        opacity=1, depth=-6.0, interpolate=True)
    order_trial_5 = visual.TextStim(win=win, name='text',
                                    text=order_lst[5],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=-6.0)

    polygon_trial_6 = visual.Rect(
        win=win, name='polygon_trial_6', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=1.0, fillColorSpace='rgb',
        opacity=1, depth=-7.0, interpolate=True)
    order_trial_6 = visual.TextStim(win=win, name='text',
                                    text=order_lst[6],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=-7.0)

    polygon_trial_7 = visual.Rect(
        win=win, name='polygon_trial_7', units='pix',
        width=[1.0, 1.0][0], height=[1.0, 1.0][1],
        ori=0, pos=[0, 0],
        lineWidth=1, lineColor=[1, 1, 1], lineColorSpace='rgb',
        fillColor=1.0, fillColorSpace='rgb',
        opacity=1, depth=-8.0, interpolate=True)
    order_trial_7 = visual.TextStim(win=win, name='text',
                                    text=order_lst[7],
                                    font=font,
                                    units='pix', pos=(0, 0), height=h, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=-8.0)

    # Create some handy timers
    globalClock = core.Clock()  # to track the time since experiment started
    routineTimer = core.CountdownTimer()  # to track time remaining of each (non-slip) routine

    # ------Prepare to start Routine "instr"-------
    # update component parameters for each repeat
    key_resp.keys = []
    key_resp.rt = []
    # keep track of which components have finished
    instrComponents = [text, key_resp]
    for thisComponent in instrComponents:
        thisComponent.tStart = None
        thisComponent.tStop = None
        thisComponent.tStartRefresh = None
        thisComponent.tStopRefresh = None
        if hasattr(thisComponent, 'status'):
            thisComponent.status = NOT_STARTED
    # reset timers
    t = 0
    _timeToFirstFrame = win.getFutureFlipTime(clock="now")
    instrClock.reset(-_timeToFirstFrame)  # t0 is time of first possible flip
    frameN = -1
    continueRoutine = True
    n=0

    # -------Run Routine "instr"-------
    while continueRoutine:

        # get current time
        t = instrClock.getTime()
        tThisFlip = win.getFutureFlipTime(clock=instrClock)
        tThisFlipGlobal = win.getFutureFlipTime(clock=None)
        frameN = frameN + 1  # number of completed frames (so 0 is the first frame)
        # update/draw components on each frame

        # *text* updates
        if text.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
            # keep track of start time/frame for later
            text.frameNStart = frameN  # exact frame index
            text.tStart = t  # local t and not account for scr refresh
            text.tStartRefresh = tThisFlipGlobal  # on global time
            win.timeOnFlip(text, 'tStartRefresh')  # time at next scr refresh
            text.setAutoDraw(True)

        # *key_resp* updates
        waitOnFlip = False
        if key_resp.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
            # keep track of start time/frame for later
            key_resp.famreNStart = frameN  # exact frame index
            key_resp.tStart = t  # local t and not account for scr refresh
            key_resp.tStartRefresh = tThisFlipGlobal  # on global time
            win.timeOnFlip(key_resp, 'tStartRefresh')  # time at next scr refresh
            key_resp.status = STARTED
            # keyboard checking is just starting
            win.callOnFlip(key_resp.clearEvents, eventType='keyboard')  # clear events on next screen flip
        if key_resp.status == STARTED and not waitOnFlip:
            theseKeys = key_resp.getKeys(keyList=['space'], waitRelease=False)
            if len(theseKeys):
                theseKeys = theseKeys[0]  # at least one key was pressed

                # check for quit:
                if "escape" == theseKeys:
                    endExpNow = True
                # a response ends the routine
                continueRoutine = False

            # check if all components have finished
        if not continueRoutine:  # a component has requested a forced-end of Routine
            break
        continueRoutine = False  # will revert to True if at least one component still running
        for thisComponent in instrComponents:
            if hasattr(thisComponent, "status") and thisComponent.status != FINISHED:
                continueRoutine = True
                break  # at least one component has not yet finished

        # refresh the screen
        if continueRoutine:  # don't flip if this routine is over or we'll get a blank screen
            win.flip()

    # -------Ending Routine "instr"-------
    for thisComponent in instrComponents:
        if hasattr(thisComponent, "setAutoDraw"):
            thisComponent.setAutoDraw(False)
    # the Routine "instr" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset()

    # set up handler to look after randomisation of conditions etc
    trials = data.TrialHandler(nReps=100, method='random',
                               extraInfo=expInfo, originPath=-1,
                               trialList=[None],
                               seed=None, name='trials')

    thisTrial = trials.trialList[0]  # so we can initialise stimuli with some values
    # abbreviate parameter names if possible (e.g. rgb = thisTrial.rgb)
    if thisTrial != None:
        for paramName in thisTrial:
            exec('{} = thisTrial[paramName]'.format(paramName))
    result = 0
    ifbegin=False
    for thisTrial in trials:
        if text:
            restim = visual.TextStim(win, "识别结果：" + order_lst[result - 1]+"\n"+"下一目标:"+order_lst[next_target], font='Arial',
                                    units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                                    color='white', colorSpace='rgb', opacity=1,
                                    languageStyle='LTR',
                                    depth=0.0)
        else:
            restim = visual.TextStim(win, "识别结果：" + order_lst[result - 1], font='Arial',
                                 units='pix', pos=(0, 0), height=50, wrapWidth=None, ori=0,
                                 color='white', colorSpace='rgb', opacity=1,
                                 languageStyle='LTR',
                                 depth=0.0)
        if thisTrial != None:
            for paramName in thisTrial:
                exec('{} = thisTrial[paramName]'.format(paramName))

        # ------Prepare to start Routine "cue"-------
        routineTimer.add(1.000000)
        # update component parameters for each repeat
        polygon_0.setPos((mylocation[0][0], mylocation[0][1]))
        order_0.setPos((mylocation[0][0], mylocation[0][1]))
        polygon_0.setSize((size_w, size_h))

        polygon_1.setPos((mylocation[1][0], mylocation[1][1]))
        order_1.setPos((mylocation[1][0], mylocation[1][1]))
        polygon_1.setSize((size_w, size_h))

        polygon_2.setPos((mylocation[2][0], mylocation[2][1]))
        order_2.setPos((mylocation[2][0], mylocation[2][1]))
        polygon_2.setSize((size_w, size_h))

        polygon_3.setPos((mylocation[3][0], mylocation[3][1]))
        order_3.setPos((mylocation[3][0], mylocation[3][1]))
        polygon_3.setSize((size_w, size_h))

        polygon_4.setPos((mylocation[4][0], mylocation[4][1]))
        order_4.setPos((mylocation[4][0], mylocation[4][1]))
        polygon_4.setSize((size_w, size_h))

        polygon_5.setPos((mylocation[5][0], mylocation[5][1]))
        order_5.setPos((mylocation[5][0], mylocation[5][1]))
        polygon_5.setSize((size_w, size_h))

        polygon_6.setPos((mylocation[6][0], mylocation[6][1]))
        order_6.setPos((mylocation[6][0], mylocation[6][1]))
        polygon_6.setSize((size_w, size_h))

        polygon_7.setPos((mylocation[7][0], mylocation[7][1]))
        order_7.setPos((mylocation[7][0], mylocation[7][1]))
        polygon_7.setSize((size_w, size_h))

        selecList = [polygon_0, polygon_1, polygon_2, polygon_3, polygon_4, polygon_5, polygon_6, polygon_7]
        selecList[loop_id % 8].setFillColor([1.000, 1.000, 1.000])  # rgb
        loop_id += 1
        selecList[loop_id % 8].setFillColor([255.000, 0, 0])  # rgb

        cueComponents = [polygon_0, polygon_1, polygon_2, polygon_3, polygon_4, polygon_5, polygon_6, polygon_7]

        for thisComponent in cueComponents:
            thisComponent.tStart = None
            thisComponent.tStop = None
            thisComponent.tStartRefresh = None
            thisComponent.tStopRefresh = None
            if hasattr(thisComponent, 'status'):
                thisComponent.status = NOT_STARTED
        # reset timers
        t = 0
        _timeToFirstFrame = win.getFutureFlipTime(clock="now")
        cueClock.reset(-_timeToFirstFrame)  # t0 is time of first possible flip
        frameN = -1
        continueRoutine = True
        # -------Run Routine "cue"-------
        while continueRoutine and routineTimer.getTime() > 0:
            # get current time
            t = cueClock.getTime()
            tThisFlip = win.getFutureFlipTime(clock=cueClock)
            tThisFlipGlobal = win.getFutureFlipTime(clock=None)
            frameN = frameN + 1  # number of completed frames (so 0 is the first frame)

            # *polygon_0* updates
            if polygon_0.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_0.frameNStart = frameN  # exact frame index
                polygon_0.tStart = t  # local t and not account for scr refresh
                polygon_0.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_0, 'tStartRefresh')  # time at next scr refresh
                polygon_0.setAutoDraw(True)
                restim.setAutoDraw(True)
                print(polygon_0.status)
            if polygon_0.status == STARTED:
                if tThisFlipGlobal > polygon_0.tStartRefresh + 1.0 - frameTolerance:
                    polygon_0.tStop = t  # not accounting for scr refresh
                    polygon_0.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_0, 'tStopRefresh')  # time at next scr refresh
                    polygon_0.setAutoDraw(False)
                    print('frameN3:%d' % frameN)

            # *polygon_1* updates
            if polygon_1.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_1.frameNStart = frameN  # exact frame index
                polygon_1.tStart = t  # local t and not account for scr refresh
                polygon_1.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_1, 'tStartRefresh')  # time at next scr refresh
                polygon_1.setAutoDraw(True)
            if polygon_1.status == STARTED:
                if tThisFlipGlobal > polygon_1.tStartRefresh + 1.0 - frameTolerance:
                    polygon_1.tStop = t  # not accounting for scr refresh
                    polygon_1.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_1, 'tStopRefresh')  # time at next scr refresh
                    polygon_1.setAutoDraw(False)

            # *polygon_2* updates
            if polygon_2.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_2.frameNStart = frameN  # exact frame index
                polygon_2.tStart = t  # local t and not account for scr refresh
                polygon_2.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_2, 'tStartRefresh')  # time at next scr refresh
                polygon_2.setAutoDraw(True)
            if polygon_2.status == STARTED:
                if tThisFlipGlobal > polygon_2.tStartRefresh + 1.0 - frameTolerance:
                    polygon_2.tStop = t  # not accounting for scr refresh
                    polygon_2.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_2, 'tStopRefresh')  # time at next scr refresh
                    polygon_2.setAutoDraw(False)

            # *polygon_3* updates
            if polygon_3.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_3.frameNStart = frameN  # exact frame index
                polygon_3.tStart = t  # local t and not account for scr refresh
                polygon_3.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_3, 'tStartRefresh')  # time at next scr refresh
                polygon_3.setAutoDraw(True)
            if polygon_3.status == STARTED:
                if tThisFlipGlobal > polygon_3.tStartRefresh + 1.0 - frameTolerance:
                    polygon_3.tStop = t  # not accounting for scr refresh
                    polygon_3.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_3, 'tStopRefresh')  # time at next scr refresh
                    polygon_3.setAutoDraw(False)

            # *polygon_4* updates
            if polygon_4.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_4.frameNStart = frameN  # exact frame index
                polygon_4.tStart = t  # local t and not account for scr refresh
                polygon_4.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_4, 'tStartRefresh')  # time at next scr refresh
                polygon_4.setAutoDraw(True)
            if polygon_4.status == STARTED:
                if tThisFlipGlobal > polygon_4.tStartRefresh + 1.0 - frameTolerance:
                    polygon_4.tStop = t  # not accounting for scr refresh
                    polygon_4.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_4, 'tStopRefresh')  # time at next scr refresh
                    polygon_4.setAutoDraw(False)

            # *polygon_5* updates
            if polygon_5.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_5.frameNStart = frameN  # exact frame index
                polygon_5.tStart = t  # local t and not account for scr refresh
                polygon_5.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_5, 'tStartRefresh')  # time at next scr refresh
                polygon_5.setAutoDraw(True)
            if polygon_5.status == STARTED:
                if tThisFlipGlobal > polygon_5.tStartRefresh + 1.0 - frameTolerance:
                    polygon_5.tStop = t  # not accounting for scr refresh
                    polygon_5.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_5, 'tStopRefresh')  # time at next scr refresh
                    polygon_5.setAutoDraw(False)

            # *polygon_6* updates
            if polygon_6.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_6.frameNStart = frameN  # exact frame index
                polygon_6.tStart = t  # local t and not account for scr refresh
                polygon_6.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_6, 'tStartRefresh')  # time at next scr refresh
                polygon_6.setAutoDraw(True)
            if polygon_6.status == STARTED:
                if tThisFlipGlobal > polygon_6.tStartRefresh + 1.0 - frameTolerance:
                    polygon_6.tStop = t  # not accounting for scr refresh
                    polygon_6.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_6, 'tStopRefresh')  # time at next scr refresh
                    polygon_6.setAutoDraw(False)

            # *polygon_7* updates
            if polygon_7.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_7.frameNStart = frameN  # exact frame index
                polygon_7.tStart = t  # local t and not account for scr refresh
                polygon_7.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_7, 'tStartRefresh')  # time at next scr refresh
                polygon_7.setAutoDraw(True)
            if polygon_7.status == STARTED:
                if tThisFlipGlobal > polygon_7.tStartRefresh + 1.0 - frameTolerance:
                    polygon_7.tStop = t  # not accounting for scr refresh
                    polygon_7.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_7, 'tStopRefresh')  # time at next scr refresh
                    polygon_7.setAutoDraw(False)

            # check for quit (typically the Esc key)
            if endExpNow or defaultKeyboard.getKeys(keyList=["escape"]):
                quit_function()

            # check if all components have finished
            if not continueRoutine:  # a component has requested a forced-end of Routine
                break
            continueRoutine = False  # will revert to True if at least one component still running
            for thisComponent in cueComponents:
                if hasattr(thisComponent, "status") and thisComponent.status != FINISHED:
                    continueRoutine = True
                    break  # at least one component has not yet finished

            # refresh the screen
            if continueRoutine:  # don't flip if this routine is over or we'll get a blank screen
                win.flip()
                ifbegin=True
                currentLoop = trials
        i0=0
        # -------Ending Routine "cue"-------
        for thisComponent in cueComponents:
            if hasattr(thisComponent, "setAutoDraw"):
                thisComponent.setAutoDraw(False)

        # ------Prepare to start Routine "trial"-------
        # update component parameters for each repeat
        polygon_trial_0.setPos((mylocation[0][0], mylocation[0][1]))
        order_trial_0.setPos((mylocation[0][0], mylocation[0][1]))
        polygon_trial_0.setSize((size_w, size_h))

        polygon_trial_1.setPos((mylocation[1][0], mylocation[1][1]))
        order_trial_1.setPos((mylocation[1][0], mylocation[1][1]))
        polygon_trial_1.setSize((size_w, size_h))

        polygon_trial_2.setPos((mylocation[2][0], mylocation[2][1]))
        order_trial_2.setPos((mylocation[2][0], mylocation[2][1]))
        polygon_trial_2.setSize((size_w, size_h))

        polygon_trial_3.setPos((mylocation[3][0], mylocation[3][1]))
        order_trial_3.setPos((mylocation[3][0], mylocation[3][1]))
        polygon_trial_3.setSize((size_w, size_h))

        polygon_trial_4.setPos((mylocation[4][0], mylocation[4][1]))
        order_trial_4.setPos((mylocation[4][0], mylocation[4][1]))
        polygon_trial_4.setSize((size_w, size_h))

        polygon_trial_5.setPos((mylocation[5][0], mylocation[5][1]))
        order_trial_5.setPos((mylocation[5][0], mylocation[5][1]))
        polygon_trial_5.setSize((size_w, size_h))

        polygon_trial_6.setPos((mylocation[6][0], mylocation[6][1]))
        order_trial_6.setPos((mylocation[6][0], mylocation[6][1]))
        polygon_trial_6.setSize((size_w, size_h))

        polygon_trial_7.setPos((mylocation[7][0], mylocation[7][1]))
        order_trial_7.setPos((mylocation[7][0], mylocation[7][1]))
        polygon_trial_7.setSize((size_w, size_h))

        seleclist2 = [polygon_trial_0, polygon_trial_1, polygon_trial_2, polygon_trial_3, polygon_trial_4,
                      polygon_trial_5,
                      polygon_trial_6, polygon_trial_7]
        trialComponents = [polygon_trial_0, polygon_trial_1, polygon_trial_2, polygon_trial_3, polygon_trial_4,
                           polygon_trial_5, polygon_trial_6, polygon_trial_7]
        for thisComponent in trialComponents:
            thisComponent.tStart = None
            thisComponent.tStop = None
            thisComponent.tStartRefresh = None
            thisComponent.tStopRefresh = None
            if hasattr(thisComponent, 'status'):
                thisComponent.status = NOT_STARTED
        # reset timers
        t = 0
        _timeToFirstFrame = win.getFutureFlipTime(clock="now")
        trialClock.reset(-_timeToFirstFrame)  # t0 is time of first possible flip
        frameN = -1
        continueRoutine = True
        if text:
            queue_name="start-"+str(next_target)+'-'+str(k)
        else:
            queue_name="start-"+str(n)
        queue.put(queue_name)
        n+=1
        begin_time = time.time()
        flag = True
        t_start = trialClock.getTime()
        # -------Run Routine "trial"-------
        while continueRoutine:
            # get current time
            t = trialClock.getTime()
            tThisFlip = win.getFutureFlipTime(clock=trialClock)
            tThisFlipGlobal = win.getFutureFlipTime(clock=None)
            frameN = frameN + 1  # number of completed frames (so 0 is the first frame)
            # update/draw components on each frame
            restim.setAutoDraw(False)

            # *polygon_trial_0* updates
            if polygon_trial_0.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_0.frameNStart = frameN  # exact frame index
                polygon_trial_0.tStart = t  # local t and not account for scr refresh
                polygon_trial_0.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_0, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_0.setAutoDraw(True)
                order_trial_0.setAutoDraw(True)
            if polygon_trial_0.status == STARTED:
                if tThisFlipGlobal > polygon_trial_0.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_0.tStop = t  # not accounting for scr refresh
                    polygon_trial_0.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_0, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_0.setAutoDraw(False)
                    order_trial_0.setAutoDraw(False)
            if polygon_trial_0.status == STARTED:  # only update if drawing
                polygon_trial_0.setFillColor([1, 1, 1], log=False)

            # *polygon_trial_1* updates
            if polygon_trial_1.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_1.frameNStart = frameN  # exact frame index
                polygon_trial_1.tStart = t  # local t and not account for scr refresh
                polygon_trial_1.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_1, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_1.setAutoDraw(True)
                order_trial_1.setAutoDraw(True)
            if polygon_trial_1.status == STARTED:
                if tThisFlipGlobal > polygon_trial_1.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_1.tStop = t  # not accounting for scr refresh
                    polygon_trial_1.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_1, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_1.setAutoDraw(False)
                    order_trial_1.setAutoDraw(False)
            if polygon_trial_1.status == STARTED:  # only update if drawing
                polygon_trial_1.setFillColor([1, 1, 1], log=False)

            # *polygon_trial_2* updates
            if polygon_trial_2.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_2.frameNStart = frameN  # exact frame index
                polygon_trial_2.tStart = t  # local t and not account for scr refresh
                polygon_trial_2.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_2, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_2.setAutoDraw(True)
                order_trial_2.setAutoDraw(True)
            if polygon_trial_2.status == STARTED:
                if tThisFlipGlobal > polygon_trial_2.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_2.tStop = t  # not accounting for scr refresh
                    polygon_trial_2.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_2, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_2.setAutoDraw(False)
                    order_trial_2.setAutoDraw(False)
            if polygon_trial_2.status == STARTED:  # only update if drawing
                polygon_trial_2.setFillColor([1, 1, 1], log=False)

            # *polygon_trial_3* updates
            if polygon_trial_3.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_3.frameNStart = frameN  # exact frame index
                polygon_trial_3.tStart = t  # local t and not account for scr refresh
                polygon_trial_3.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_3, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_3.setAutoDraw(True)
                order_trial_3.setAutoDraw(True)
            if polygon_trial_3.status == STARTED:
                if tThisFlipGlobal > polygon_trial_3.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_3.tStop = t  # not accounting for scr refresh
                    polygon_trial_3.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_3, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_3.setAutoDraw(False)
                    order_trial_3.setAutoDraw(False)
            if polygon_trial_3.status == STARTED:  # only update if drawing
                polygon_trial_3.setFillColor([1, 1, 1], log=False)

            # *polygon_trial_4* updates
            if polygon_trial_4.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_4.frameNStart = frameN  # exact frame index
                polygon_trial_4.tStart = t  # local t and not account for scr refresh
                polygon_trial_4.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_4, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_4.setAutoDraw(True)
                order_trial_4.setAutoDraw(True)
            if polygon_trial_4.status == STARTED:
                if tThisFlipGlobal > polygon_trial_4.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_4.tStop = t  # not accounting for scr refresh
                    polygon_trial_4.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_4, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_4.setAutoDraw(False)
                    order_trial_4.setAutoDraw(False)
            if polygon_trial_4.status == STARTED:  # only update if drawing
                polygon_trial_4.setFillColor([1, 1, 1], log=False)

            # *polygon_trial_5* updates
            if polygon_trial_5.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_5.frameNStart = frameN  # exact frame index
                polygon_trial_5.tStart = t  # local t and not account for scr refresh
                polygon_trial_5.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_5, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_5.setAutoDraw(True)
                order_trial_5.setAutoDraw(True)
            if polygon_trial_5.status == STARTED:
                if tThisFlipGlobal > polygon_trial_5.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_5.tStop = t  # not accounting for scr refresh
                    polygon_trial_5.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_5, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_5.setAutoDraw(False)
                    order_trial_5.setAutoDraw(False)
            if polygon_trial_5.status == STARTED:  # only update if drawing
                polygon_trial_5.setFillColor([1, 1, 1], log=False)

            # *polygon_trial_6* updates
            if polygon_trial_6.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_6.frameNStart = frameN  # exact frame index
                polygon_trial_6.tStart = t  # local t and not account for scr refresh
                polygon_trial_6.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_6, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_6.setAutoDraw(True)
                order_trial_6.setAutoDraw(True)
            if polygon_trial_6.status == STARTED:
                if tThisFlipGlobal > polygon_trial_6.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_6.tStop = t  # not accounting for scr refresh
                    polygon_trial_6.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_6, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_6.setAutoDraw(False)
                    order_trial_6.setAutoDraw(False)
            if polygon_trial_6.status == STARTED:  # only update if drawing
                polygon_trial_6.setFillColor([1, 1, 1], log=False)

            # *polygon_trial_7* updates
            if polygon_trial_7.status == NOT_STARTED and tThisFlip >= 0.0 - frameTolerance:
                polygon_trial_7.frameNStart = frameN  # exact frame index
                polygon_trial_7.tStart = t  # local t and not account for scr refresh
                polygon_trial_7.tStartRefresh = tThisFlipGlobal  # on global time
                win.timeOnFlip(polygon_trial_7, 'tStartRefresh')  # time at next scr refresh
                polygon_trial_7.setAutoDraw(True)
                order_trial_7.setAutoDraw(True)
            if polygon_trial_7.status == STARTED:
                if tThisFlipGlobal > polygon_trial_7.tStartRefresh + trial_dura - frameTolerance:
                    polygon_trial_7.tStop = t  # not accounting for scr refresh
                    polygon_trial_7.frameNStop = frameN  # exact frame index
                    win.timeOnFlip(polygon_trial_7, 'tStopRefresh')  # time at next scr refresh
                    polygon_trial_7.setAutoDraw(False)
                    order_trial_7.setAutoDraw(False)
            if polygon_trial_7.status == STARTED:  # only update if drawing
                polygon_trial_7.setFillColor([1, 1, 1], log=False)

            Amp = (sin(2 * pi * Freq * frameN / 60 + Phas) - 0.5) * 2
            i0+=1
            for idx in range(8):
                seleclist2[idx].setFillColor([Amp[idx]])

            # check for quit (typically the Esc key)
            if endExpNow or defaultKeyboard.getKeys(keyList=["escape"]):
                quit_function()
            # check if all components have finished
            if not continueRoutine:  # a component has requested a forced-end of Routine
                break
            continueRoutine = False  # will revert to True if at least one component still running
            for thisComponent in trialComponents:
                if hasattr(thisComponent, "status") and thisComponent.status != FINISHED:
                    continueRoutine = True
                    break  # at least one component has not yet finished
            # refresh the screen
            if continueRoutine:  # don't flip if this routine is over or we'll get a blank screen
                if flag:
                    flag = False
                    print(t_start - trialClock.getTime())
                win.flip()
        queue.put("end")
        print("show trial spend time: ", time.time() - begin_time)
        time.sleep(3)  # 暂停一秒，让存储程序写入脑电数据到硬盘

        def resample_eeg_data(x, resample_fs):
            """
            重新采样 eeg 数据
            resample_fs 重新采样的频率
            """
            resample_list = []
            for channel in range(x.shape[0]):
                resample_list.append(resample(x[channel], resample_fs))
            return np.array(resample_list)

        read_path=queue_name+'.csv'
        np_array = pd.read_csv(os.path.join(save_path, read_path)).to_numpy()

        data_len = np_array.shape[0]

        # 取后面四秒的数据进行计算
        print("识别数据形状:{}".format(np_array.shape))
        np_array = np_array[data_len - stim_t * 500: data_len, 0:8]

        print("识别数据形状:{}".format(np_array.shape))
        np_array = np_array.transpose(1, 0)
        # 下采样成 250 hz
        np_array = resample_eeg_data(np_array, 250 * stim_t)
        print("识别数据形状:{}".format(np_array.shape))

        result = fbcca.fbcca_classify(np_array, stim_t*250)

        print(result)

        if text:
            k+=1
            if k==7:
                next_target += 1
                k = 0
                if next_target == 8:
                    next_target = 0

        order_lst = ['8Hz', '9Hz', '10Hz', '11Hz', '12Hz', '13Hz', '14Hz', '15Hz']

        for thisComponent in trialComponents:
            if hasattr(thisComponent, "setAutoDraw"):
                thisComponent.setAutoDraw(False)

        routineTimer.reset()

    win.flip()

    logging.flush()
    win.close()
    quit_function()

