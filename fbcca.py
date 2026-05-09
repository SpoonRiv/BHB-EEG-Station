# author:mingyang,fan
# data:2023.6.1
# input:eeg(channels*points)
# Fs:采样频率；T采样点（在刺激内）

import numpy as np
import math
from scipy import signal
from sklearn.cross_decomposition import CCA
import scipy.io
# eeg:channels*points
Fs = 250
# T = 750


def filter_bank(eeg):
    Nm = 3
    result = np.zeros((Nm, eeg.shape[0], eeg.shape[1]))
    nyq = Fs / 2
    passband = [6, 14, 22, 30, 38, 46, 54, 62, 70, 78]
    stopband = [4, 10, 16, 24, 32, 40, 48, 56, 64, 72]
    highcut_pass, highcut_stop = 80, 90
    gpass, gstop, Rp = 3, 40, 0.5

    for i in range(Nm):
        Wp = [passband[i] / nyq, highcut_pass / nyq]
        Ws = [stopband[i] / nyq, highcut_stop / nyq]
        [N, Wn] = signal.cheb1ord(Wp, Ws, gpass, gstop)
        [B, A] = signal.cheby1(N, Rp, Wn, 'bandpass')
        data = signal.filtfilt(B, A, eeg, padlen=3 * (max(len(B), len(A)) - 1)).copy()
        result[i, :, :] = data

    return result


def get_Reference_Signal(length,num_harmonics=3):
    targets = [8, 9, 10, 11, 12, 13, 14, 15]
    # targets = [8.00, 8.30, 8.60, 8.90, 9.20, 9.50, 9.80, 10.10]
    reference_signals = []
    t = np.arange(0, (length / Fs), step=1.0 / Fs)
    for f in targets:
        reference_f = []
        for h in range(1, num_harmonics + 1):
            reference_f.append(np.sin(2 * np.pi * h * f * t)[0:length])
            reference_f.append(np.cos(2 * np.pi * h * f * t)[0:length])
        reference_signals.append(reference_f)
    reference_signals = np.asarray(reference_signals)
    return reference_signals


def find_correlation(X, Y):
    cca = CCA(1)
    corr = np.zeros(1)
    num_freq = Y.shape[0]
    result = np.zeros(num_freq)
    for freq_idx in range(0, num_freq):
        matched_X = X
        cca.fit(matched_X.T, Y[freq_idx].T)
        # cca.fit(X.T, Y[freq_idx].T)
        x_a, y_b = cca.transform(matched_X.T, Y[freq_idx].T)
        for i in range(0, 1):
            corr[i] = np.corrcoef(x_a[:, i], y_b[:, i])[0, 1]
            result[freq_idx] = np.max(corr)
    return result


def fbcca_classify(data, data_length):
    reference_signals = get_Reference_Signal(data_length)
    data = filter_bank(data)
    predicted_class = []
    labels = []
    Nm = 3
    fb_coefs = [math.pow(i, -1.25) + 0.25 for i in range(1, Nm + 1)]  # w(n) = n^(-0.5) + 1.25
    result = np.zeros(8)
    for fb_i in range(0, Nm):
        x = data[fb_i, :, :]
        y = reference_signals
        w = fb_coefs[fb_i]
        result += (w * (find_correlation(x, y) ** 2))

    predicted = np.argmax(result) + 1
    return predicted
#
# data= scipy.io.loadmat('./Data/S1.mat')
# eeg=data['data']
# eeg1=eeg[[53,54,55,56,57,60,61,62],:,5,1]
# eeg2=eeg[[53,54,55,56,57,60,61,62],:,5,2]
# eeg3=np.hstack((eeg1,eeg2))
# # print(eeg.shape)
# result=fbcca_classify(eeg1)
# print(result)
