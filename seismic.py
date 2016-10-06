#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Seismic object for seisplot and beyond.

:copyright: 2016 Agile Geoscience
:license: Apache 2.0
"""
from functools import partial

import matplotlib.pyplot as plt
import numpy as np
import obspy

import utils
import patterns


class Seismic(object):

    def __init__(self, data, dtype=float, params=None):
        
        if params is None:
            params = {}
        
        self.data = np.asarray(data, dtype=dtype)
        self.header = params.get('header', '')
        self.ntraces = params.get('ntraces', self.data.shape[0])
        self.inlines = params.get('inlines', None)
        self.xlines = params.get('xlines', None)
        self.ninlines = params.get('ninlines', 1)
        self.nxlines = params.get('nxlines', 0)
        self.nsamples = params.get('nsamples', self.data.shape[-1])
        self.tstart = params.get('tstart', 0)
        self.dt = params.get('dt', 0)

        if self.nsamples and self.nsamples != self.data.shape[-1]:
            t = self.nsamples
            self.nsamples = int(self.data.shape[-1])
            if t != self.nsamples:
                s = "Number of time samples changed to {} to match data."
                print(s.format(self.nsamples))

        # For when we have xline number but not inline number.
        # This happens when ObsPy reads a 3D.
        if self.ninlines == 1:
            if self.nxlines > 0:
                self.ninlines = int(self.data.shape[0] / self.nxlines)
        
        if self.ninlines > 1:
            x = self.nxlines
            self.nxlines = int(self.data.shape[0] / self.ninlines)
            if self.nxlines and x != self.nxlines:
                s = "nxlines changed to {} to match data."
                print(s.format(self.nxlines))
            self.data = self.data.reshape((self.ninlines, self.nxlines, self.data.shape[-1]))

        if self.inlines is None:
            self.inlines = np.linspace(1, self.ninlines, self.ninlines)
        if self.xlines is None:
            self.xlines = np.linspace(1, self.nxlines, self.nxlines)

        self.tbasis = np.arange(0, self.nsamples * self.dt, self.dt)
        return
    
    @property
    def shape(self):
        return self.data.shape
    
    @property
    def ndim(self):
        return self.data.ndim

    @property
    def tend(self):
        return np.amax(self.tbasis)

    def trace_range(self, direction):
        if direction.lower()[0] == 'x':
            self.inlines[0], self.inlines[-1]
        return self.xlines[0], self.xlines[-1]

    @classmethod
    def from_obspy(cls, stream, params=None):
        data = np.stack(t.data for t in stream.traces)
        if params is None:
            params = {}
        dt = params.get('dt', stream.binary_file_header.sample_interval_in_microseconds)

        # Make certain it winds up in seconds. Most likely 0.0005 to 0.008.
        while dt > 0.02:
            dt *= 0.001

        params['dt'] = dt

        # Since we have the headers, etc, we can try to get some info.

        # Get a monotonic sequence from the headers. Will be CDPs for a 2D.
        threed = False

        # Get a sawtooth progression. Will only work for a 3D.
        xlines = utils.get_pattern_from_stream(stream, patterns.sawtooth)
        if np.any(xlines):
            threed = True
            nxlines = np.amax(xlines) - np.amin(xlines) + 1
            params['nxlines'] = params.get('nxlines') or nxlines
            params['xlines'] = params.get('xlines') or xlines
        else:
            xlines = utils.get_pattern_from_stream(stream, patterns.monotonic)
            if np.any(xlines):
                nxlines = np.amax(xlines) - np.amin(xlines) + 1
                params['nxlines'] = params.get('nxlines') or nxlines
                params['xlines'] = params.get('xlines') or xlines

        params['ninlines'] = 1
        if threed:
            inlines = utils.get_pattern_from_stream(stream, patterns.stairstep)
            if np.any(inlines):
                ninlines = np.amax(inlines) - np.amin(inlines) + 1
                params['ninlines'] = params.get('ninlines') or ninlines
                params['inlines'] = params.get('inlines') or inlines

        x = np.array(list(stream.textual_file_header.decode()))
        params['header'] = '\n'.join(''.join(row) for row in x.reshape((40, 80)))

        headers = {
            'elevation': 'receiver_group_elevation',
            'fold': 'number_of_horizontally_stacked_traces_yielding_this_trace',
            'water_depth': 'water_depth_at_group',
        }

        for k, v in headers.items():
            params[k] = [t.header.__dict__[v] for t in stream.traces]

        return cls(data, params=params)

    @classmethod
    def from_segy(cls, segy_file, params=None):
        stream = obspy.io.segy.segy._read_segy(segy_file, unpack_headers=True)
        return cls.from_obspy(stream, params=params)

    def spectrum(self, signal, fs):
        windowed = signal * np.blackman(len(signal))
        a = abs(np.fft.rfft(windowed))
        f = np.fft.rfftfreq(len(signal), 1/fs)

        db = 20 * np.log10(a)
        sig = db - np.amax(db) + 20
        indices = ((sig[1:] >= 0) & (sig[:-1] < 0)).nonzero()
        crossings = [z - sig[z] / (sig[z+1] - sig[z]) for z in indices]
        mi, ma = np.amin(crossings), np.amax(crossings)
        x = np.arange(0, len(f))  # for back-interpolation
        f_min = np.interp(mi, x, f)
        f_max = np.interp(ma, x, f)

        return f, a, f_min, f_max
    
    def plot_spectrum(self, ax=None, tickfmt=None, ntraces=10, fontsize=10):
        """
        Plot a power spectrum.
        w is window length for smoothing filter
        """
        if ax is None:
            fig = plt.figure(figsize=(12,6))
            ax = fig.add_subplot(111)

        trace_indices = utils.get_trace_indices(self.data.shape[1],
                                                ntraces,
                                                random=True)
        fs = 1 / self.dt

        specs, peaks, mis, mas = [], [], [], []
        for ti in trace_indices:
            trace = self.data[:, ti]
            f, amp, fmi, fma = self.spectrum(trace, fs)

            peak = f[np.argmax(amp)]

            specs.append(amp)
            peaks.append(peak)
            mis.append(fmi)
            mas.append(fma)

        spec = np.mean(np.dstack(specs), axis=-1)
        spec = np.squeeze(spec)
        db = 20 * np.log10(amp)
        db = db - np.amax(db)
        f_peak = np.mean(peaks)
        f_min = np.amin(mis)
        f_max = np.amax(mas)

        statstring = "\nMin: {:.2f} Hz\nPeak: {:.2f} Hz\nMax: {:.2f}"
        stats = statstring.format(f_min, f_peak, f_max)

        ax.plot(f, db, lw=0)  # Plot invisible line to get the min
        y_min = ax.get_yticks()[0]
        ax.fill_between(f, y_min, db, lw=0, facecolor='k', alpha=0.5)
        ax.set_xlabel('frequency [Hz]', fontsize=fontsize - 4)
        ax.xaxis.set_label_coords(0.5, -0.12)
        ax.set_xlim([0, np.amax(f)])
        ax.set_xticklabels(ax.get_xticks(), fontsize=fontsize - 4)
        ax.set_yticklabels(ax.get_yticks(), fontsize=fontsize - 4)
        ax.set_ylabel('power [dB]', fontsize=fontsize - 4)
        ax.text(.98, .95, 'AMPLITUDE SPECTRUM'+stats,
                     horizontalalignment='right',
                     verticalalignment='top',
                     transform=ax.transAxes, fontsize=fontsize - 3)
        ax.yaxis.set_major_formatter(tickfmt)
        ax.xaxis.set_major_formatter(tickfmt)
        ax.grid('on')
        return ax
    
    def get_line(self, l=1, direction=None):
        if self.ndim < 3:
            return self.data
        if (direction is None) or (direction.lower()[0] == 'i'):
            if l < 1: l *= self.ninlines
            return self.data[l, :, :]
        else:
            if l < 1: l *= self.nxlines
            return self.data[:, l, :]

    inline = partial(get_line, direction='i')
    xline = partial(get_line, direction='x')

    def wiggle_plot(self, l=1, direction='i',
                    ax=None,
                    skip=1,
                    perc=99.0,
                    gain=1.0,
                    rgb=(0, 0, 0),
                    alpha=0.5,
                    lw=0.2):
        """
        Plots wiggle traces of seismic data. Skip=1, every trace, skip=2, every
        second trace, etc.
        """
        if ax is None:
            fig = plt.figure(figsize=(16,8))
            ax = fig.add_subplot(111)

        data = self.get_line(l, direction)
        rgba = list(rgb) + [alpha]
        sc = np.percentile(data, perc)  # Normalization factor
        wigdata = data[::skip, :]
        xpos = np.arange(self.ntraces)[::skip]

        for x, trace in zip(xpos, wigdata):
            # Compute high resolution trace.
            amp = gain * trace / sc + x
            t = self.tbasis
            hypertime = 1000*np.linspace(t[0], t[-1], (10 * t.size - 1) + 1)
            hyperamp = np.interp(hypertime, 1000*t, amp)

            # Plot the line, then the fill.
            ax.plot(hyperamp, hypertime, 'k', lw=lw)
            ax.fill_betweenx(hypertime, hyperamp, x,
                             where=hyperamp > x,
                             facecolor=rgba,
                             lw=0,
                             )
        return ax

    def plot(self, slc=None):
        if slc is None:
            slc = self.data.shape[0] // 2
        vm = np.percentile(self.data, 99)
        imparams = {'interpolation': 'none',
                  'cmap': "gray",
                  'vmin': -vm,
                  'vmax': vm,
                  'aspect': 'auto'
                 }
        if self.ndim == 1:
            plt.plot(self.data)
        elif self.ndim == 2:
            plt.imshow(self.data.T, **imparams)
            plt.colorbar()
        else:
            plt.imshow(self.data[slc].T, **imparams)
            plt.colorbar()
        plt.show()
        return