import os
from boxbranding import getMachineBrand, getMachineName
from time import ctime, time
from bisect import insort

from enigma import eActionMap, quitMainloop

from Components.config import config
from Components.Harddisk import internalHDDNotSleeping
from Components.TimerSanityCheck import TimerSanityCheck
from Screens.MessageBox import MessageBox
import Screens.Standby
from Tools import Directories, Notifications
from Tools.XMLTools import stringToXML
from timer import Timer, TimerEntry
import NavigationInstance


# parses an event, and gives out a (begin, end, name, duration, eit)-tuple.
# begin and end will be corrected
def parseEvent(ev):
	begin = ev.getBeginTime()
	end = begin + ev.getDuration()
	return begin, end


class AFTEREVENT:
	def __init__(self):
		pass

	NONE = 0
	WAKEUPTOSTANDBY = 1
	STANDBY = 2
	DEEPSTANDBY = 3


class TIMERTYPE:
	def __init__(self):
		pass

	NONE = 0
	WAKEUP = 1
	WAKEUPTOSTANDBY = 2
	AUTOSTANDBY = 3
	AUTODEEPSTANDBY = 4
	STANDBY = 5
	DEEPSTANDBY = 6
	REBOOT = 7
	RESTART = 8

# please do not translate log messages


class PowerTimerEntry(TimerEntry):
	def __init__(self, begin, end, disabled=False, afterEvent=AFTEREVENT.NONE, timerType=TIMERTYPE.WAKEUP, checkOldTimers=False):
		TimerEntry.__init__(self, int(begin), int(end))
		if checkOldTimers:
			if self.begin < time() - 1209600:
				self.begin = int(time())

		if self.end < self.begin:
			self.end = self.begin

		self.dontSave = False
		self.disabled = disabled
		self.timer = None
		self.__record_service = None
		self.start_prepare = 0
		self.timerType = timerType
		self.afterEvent = afterEvent
		self.autoincrease = False
		self.autoincreasetime = 3600 * 24  # 1 day
		self.autosleepinstandbyonly = 'no'
		self.autosleepdelay = 60
		self.autosleeprepeat = 'once'

		self.resetState()

	def __repr__(self):
		timertype = {
			TIMERTYPE.WAKEUP: "wakeup",
			TIMERTYPE.WAKEUPTOSTANDBY: "wakeuptostandby",
			TIMERTYPE.AUTOSTANDBY: "autostandby",
			TIMERTYPE.AUTODEEPSTANDBY: "autodeepstandby",
			TIMERTYPE.STANDBY: "standby",
			TIMERTYPE.DEEPSTANDBY: "deepstandby",
			TIMERTYPE.REBOOT: "reboot",
			TIMERTYPE.RESTART: "restart"
			}[self.timerType]
		if not self.disabled:
			return "PowerTimerEntry(type=%s, begin=%s)" % (timertype, ctime(self.begin))
		else:
			return "PowerTimerEntry(type=%s, begin=%s Disabled)" % (timertype, ctime(self.begin))

	def log(self, code, msg):
		self.log_entries.append((int(time()), code, msg))

	def do_backoff(self):
#
# back-off an auto-repeat timer by its autosleepdelay, not 5, 10, 20, 30 mins
#
		if self.autosleeprepeat == "repeated" and self.timerType in (TIMERTYPE.AUTOSTANDBY, TIMERTYPE.AUTODEEPSTANDBY):
			self.backoff = int(self.autosleepdelay) * 60
		elif self.backoff == 0:
			self.backoff = 5 * 60
		else:
			self.backoff *= 2
			if self.backoff > 1800:
				self.backoff = 1800
		self.log(10, "backoff: retry in %d minutes" % (int(self.backoff) / 60))
#
# If this is the first backoff of a repeat timer remember the original
# begin/end times, so that we can use *these* when setting up the repeat.
#
		if self.repeated != 0 and not hasattr(self, "real_begin"):
			self.real_begin = self.begin
			self.real_end = self.end

# Delay the timer by the back-off time
#
		self.begin = time() + self.backoff
		if self.end <= self.begin:
			self.end = self.begin

	def activate(self):
		next_state = self.state + 1
		self.log(5, "activating state %d" % next_state)

		if next_state == self.StatePrepared and (self.timerType == TIMERTYPE.AUTOSTANDBY or self.timerType == TIMERTYPE.AUTODEEPSTANDBY):
# This is the first action for an auto* timer.
# It binds any key press to keyPressed(), which resets the timer delay,
# and sets the initial delay.
#
			eActionMap.getInstance().bindAction('', -0x7FFFFFFF, self.keyPressed)
			self.begin = time() + int(self.autosleepdelay) * 60
			if self.end <= self.begin:
				self.end = self.begin

		if next_state == self.StatePrepared:
			self.log(6, "prepare ok, waiting for begin")
			self.next_activation = self.begin
			self.backoff = 0
			return True

		elif next_state == self.StateRunning:
			self.wasPowerTimerWakeup = False
			if os.path.exists("/tmp/was_powertimer_wakeup"):
				self.wasPowerTimerWakeup = int(open("/tmp/was_powertimer_wakeup", "r").read()) and True or False
				os.remove("/tmp/was_powertimer_wakeup")
			# if this timer has been cancelled, just go to "end" state.
			if self.cancelled:
				return True

			if self.failed:
				return True

			if self.timerType == TIMERTYPE.WAKEUP:
				if Screens.Standby.inStandby:
					Screens.Standby.inStandby.Power()
				return True

			elif self.timerType == TIMERTYPE.WAKEUPTOSTANDBY:
				return True

			elif self.timerType == TIMERTYPE.STANDBY:
				if not Screens.Standby.inStandby:  # not already in standby
					Notifications.AddNotificationWithUniqueIDCallback(self.sendStandbyNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to set your\n%s %s to standby. Do that now?") % (getMachineBrand(), getMachineName()), timeout=180)
				return True

			elif self.timerType == TIMERTYPE.AUTOSTANDBY:
				if NavigationInstance.instance.getCurrentlyPlayingServiceReference() and ('0:0:0:0:0:0:0:0:0' in NavigationInstance.instance.getCurrentlyPlayingServiceReference().toString() or '4097:' in NavigationInstance.instance.getCurrentlyPlayingServiceReference().toString()):
					self.do_backoff()
					# retry
					return False
				if not Screens.Standby.inStandby:  # not already in standby
					Notifications.AddNotificationWithUniqueIDCallback(self.sendStandbyNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to set your\n%s %s to standby. Do that now?") % (getMachineBrand(), getMachineName()), timeout=180)
					if self.autosleeprepeat == "once":
						eActionMap.getInstance().unbindAction('', self.keyPressed)
						return True
					else:
						self.begin = time() + int(self.autosleepdelay) * 60
						if self.end <= self.begin:
							self.end = self.begin
				else:
					self.begin = time() + int(self.autosleepdelay) * 60
					if self.end <= self.begin:
						self.end = self.begin

			elif self.timerType == TIMERTYPE.AUTODEEPSTANDBY:

# Check for there being any active Movie playback or IPTV channel
# or any streaming clients before going to Deep Standby.
# However, it is possible to put the box into Standby with the
# MoviePlayer still active (it will play if the box is taken out
# of Standby) - similarly for the IPTV player. This should not
# prevent a DeepStandby
# And check for existing or imminent recordings, etc..
# Also added () around the test and split them across lines
# to make it clearer what each test is.
#
				from Components.Converter.ClientsStreaming import ClientsStreaming
				if ((not Screens.Standby.inStandby and NavigationInstance.instance.getCurrentlyPlayingServiceReference() and
					('0:0:0:0:0:0:0:0:0' in NavigationInstance.instance.getCurrentlyPlayingServiceReference().toString() or
					 '4097:' in NavigationInstance.instance.getCurrentlyPlayingServiceReference().toString()
				     ) or
				     (int(ClientsStreaming("NUMBER").getText()) > 0)
				    ) or
				    (NavigationInstance.instance.RecordTimer.isRecording() or
				     abs(NavigationInstance.instance.RecordTimer.getNextRecordingTime() - time()) <= 900 or
				     abs(NavigationInstance.instance.RecordTimer.getNextZapTime() - time()) <= 900) or
				     (self.autosleepinstandbyonly == 'yes' and not Screens.Standby.inStandby) or
				     (self.autosleepinstandbyonly == 'yes' and Screens.Standby.inStandby and internalHDDNotSleeping()
				    )
				   ):
					self.do_backoff()
					# retry
					return False
				if not Screens.Standby.inTryQuitMainloop:  # not a shutdown messagebox is open
					if Screens.Standby.inStandby:  # in standby
						quitMainloop(1)
						return True
					else:
						Notifications.AddNotificationWithUniqueIDCallback(self.sendTryQuitMainloopNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to shutdown your %s %s.\nDo that now?") % (getMachineBrand(), getMachineName()), timeout=180)
						if self.autosleeprepeat == "once":
							eActionMap.getInstance().unbindAction('', self.keyPressed)
							return True
						else:
							self.begin = time() + int(self.autosleepdelay) * 60
							if self.end <= self.begin:
								self.end = self.begin

			elif self.timerType == TIMERTYPE.DEEPSTANDBY and self.wasPowerTimerWakeup:
				return True

			elif self.timerType == TIMERTYPE.DEEPSTANDBY and not self.wasPowerTimerWakeup:
				if NavigationInstance.instance.RecordTimer.isRecording() or abs(NavigationInstance.instance.RecordTimer.getNextRecordingTime() - time()) <= 900 or abs(NavigationInstance.instance.RecordTimer.getNextZapTime() - time()) <= 900:
					self.do_backoff()
					# retry
					return False
				if not Screens.Standby.inTryQuitMainloop:  # not a shutdown messagebox is open
					if Screens.Standby.inStandby:  # in standby
						quitMainloop(1)
					else:
						Notifications.AddNotificationWithUniqueIDCallback(self.sendTryQuitMainloopNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to shutdown your %s %s.\nDo that now?") % (getMachineBrand(), getMachineName()), timeout=180)
				return True

			elif self.timerType == TIMERTYPE.REBOOT:
				if NavigationInstance.instance.RecordTimer.isRecording() or abs(NavigationInstance.instance.RecordTimer.getNextRecordingTime() - time()) <= 900 or abs(NavigationInstance.instance.RecordTimer.getNextZapTime() - time()) <= 900:
					self.do_backoff()
					# retry
					return False
				if not Screens.Standby.inTryQuitMainloop:  # not a shutdown messagebox is open
					if Screens.Standby.inStandby:  # in standby
						quitMainloop(2)
					else:
						Notifications.AddNotificationWithUniqueIDCallback(self.sendTryToRebootNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to reboot your %s %s.\nDo that now?") % (getMachineBrand(), getMachineName()), timeout=180)
				return True

			elif self.timerType == TIMERTYPE.RESTART:
				if NavigationInstance.instance.RecordTimer.isRecording() or abs(NavigationInstance.instance.RecordTimer.getNextRecordingTime() - time()) <= 900 or abs(NavigationInstance.instance.RecordTimer.getNextZapTime() - time()) <= 900:
					self.do_backoff()
					# retry
					return False
				if not Screens.Standby.inTryQuitMainloop:  # not a shutdown messagebox is open
					if Screens.Standby.inStandby:  # in standby
						quitMainloop(3)
					else:
						Notifications.AddNotificationWithUniqueIDCallback(self.sendTryToRestartNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to restart the user interface.\nDo that now?"), timeout=180)
				return True

		elif next_state == self.StateEnded:
			old_end = self.end
			NavigationInstance.instance.PowerTimer.saveTimer()
			if self.afterEvent == AFTEREVENT.STANDBY:
				if not Screens.Standby.inStandby:  # not already in standby
					Notifications.AddNotificationWithUniqueIDCallback(self.sendStandbyNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to set your\n%s %s to standby. Do that now?") % (getMachineBrand(), getMachineName()), timeout=180)
			elif self.afterEvent == AFTEREVENT.DEEPSTANDBY:
				if NavigationInstance.instance.RecordTimer.isRecording() or abs(NavigationInstance.instance.RecordTimer.getNextRecordingTime() - time()) <= 900 or abs(NavigationInstance.instance.RecordTimer.getNextZapTime() - time()) <= 900:
					self.do_backoff()
					# retry
					return False
				if not Screens.Standby.inTryQuitMainloop:  # not a shutdown messagebox is open
					if Screens.Standby.inStandby:  # in standby
						quitMainloop(1)
					else:
						Notifications.AddNotificationWithUniqueIDCallback(self.sendTryQuitMainloopNotification, "PT_StateChange", MessageBox, _("A finished powertimer wants to shutdown your %s %s.\nDo that now?") % (getMachineBrand(), getMachineName()), timeout=180)
			return True

	def setAutoincreaseEnd(self, entry=None):
		if not self.autoincrease:
			return False
		if entry is None:
			new_end = int(time()) + self.autoincreasetime
		else:
			new_end = entry.begin - 30

		dummyentry = PowerTimerEntry(self.begin, new_end, disabled=True, afterEvent=self.afterEvent, timerType=self.timerType)
		dummyentry.disabled = self.disabled
		timersanitycheck = TimerSanityCheck(NavigationInstance.instance.PowerManager.timer_list, dummyentry)
		if not timersanitycheck.check():
			simulTimerList = timersanitycheck.getSimulTimerList()
			if simulTimerList is not None and len(simulTimerList) > 1:
				new_end = simulTimerList[1].begin
				new_end -= 30				# 30 Sekunden Prepare-Zeit lassen
		if new_end <= time():
			return False
		self.end = new_end
		return True

	def sendStandbyNotification(self, answer):
		if answer:
			Notifications.AddNotification(Screens.Standby.Standby)

	def sendTryQuitMainloopNotification(self, answer):
		if answer:
			Notifications.AddNotification(Screens.Standby.TryQuitMainloop, 1)

	def sendTryToRebootNotification(self, answer):
		if answer:
			Notifications.AddNotification(Screens.Standby.TryQuitMainloop, 2)

	def sendTryToRestartNotification(self, answer):
		if answer:
			Notifications.AddNotification(Screens.Standby.TryQuitMainloop, 3)

	def keyPressed(self, key, tag):
		self.begin = time() + int(self.autosleepdelay) * 60
		if self.end <= self.begin:
			self.end = self.begin

	def getNextActivation(self):
		if self.state == self.StateEnded or self.state == self.StateFailed:
			return self.end

		next_state = self.state + 1

		return {self.StatePrepared: self.start_prepare,
				self.StateRunning: self.begin,
				self.StateEnded: self.end}[next_state]

	def getNextWakeup(self):
		if self.state == self.StateEnded or self.state == self.StateFailed:
			return self.end

		if self.timerType != TIMERTYPE.WAKEUP and self.timerType != TIMERTYPE.WAKEUPTOSTANDBY and not self.afterEvent:
			return -1
		elif self.timerType != TIMERTYPE.WAKEUP and self.timerType != TIMERTYPE.WAKEUPTOSTANDBY and self.afterEvent:
			return self.end
		next_state = self.state + 1
		return {self.StatePrepared: self.start_prepare,
				self.StateRunning: self.begin,
				self.StateEnded: self.end}[next_state]

	def timeChanged(self):
		old_prepare = self.start_prepare
		self.start_prepare = self.begin - self.prepare_time
		self.backoff = 0

		if int(old_prepare) > 60 and int(old_prepare) != int(self.start_prepare):
			self.log(15, "time changed, start prepare is now: %s" % ctime(self.start_prepare))


def createTimer(xml):
	timertype = str(xml.get("timertype") or "wakeup")
	timertype = {
		"wakeup": TIMERTYPE.WAKEUP,
		"wakeuptostandby": TIMERTYPE.WAKEUPTOSTANDBY,
		"autostandby": TIMERTYPE.AUTOSTANDBY,
		"autodeepstandby": TIMERTYPE.AUTODEEPSTANDBY,
		"standby": TIMERTYPE.STANDBY,
		"deepstandby": TIMERTYPE.DEEPSTANDBY,
		"reboot": TIMERTYPE.REBOOT,
		"restart": TIMERTYPE.RESTART
		}[timertype]
	begin = int(xml.get("begin"))
	end = int(xml.get("end"))
	repeated = str(xml.get("repeated"))
	disabled = int(xml.get("disabled") or "0")
	afterevent = str(xml.get("afterevent") or "nothing")
	afterevent = {
		"nothing": AFTEREVENT.NONE,
		"wakeuptostandby": AFTEREVENT.WAKEUPTOSTANDBY,
		"standby": AFTEREVENT.STANDBY,
		"deepstandby": AFTEREVENT.DEEPSTANDBY
		}[afterevent]
	autosleepinstandbyonly = str(xml.get("autosleepinstandbyonly") or "no")
	autosleepdelay = str(xml.get("autosleepdelay") or "0")
	autosleeprepeat = str(xml.get("autosleeprepeat") or "once")
#
# If this is a repeating auto* timer then start it in 30 secs,
# which means it will start its repeating countdown from when enigma2
# starts each time rather then waiting until anything left over from the
# last enigma2 running.
#
	if autosleeprepeat == "repeated":
		begin = end = time() + 30

	entry = PowerTimerEntry(begin, end, disabled, afterevent, timertype)
	entry.autosleepinstandbyonly = autosleepinstandbyonly
	entry.autosleepdelay = int(autosleepdelay)
	entry.autosleeprepeat = autosleeprepeat
# Ensure that the timer repeated is cleared if we have an autosleeprepeat
	if entry.autosleeprepeat == "repeated":
		entry.repeated = 0
	else:
		entry.repeated = int(repeated)

	for l in xml.findall("log"):
		ltime = int(l.get("time"))
		lcode = int(l.get("code"))
		# print("[PowerManager]: ltext, time, code", l.text, "   ", l.get("time"), "   ", l.get("code"))
		msg = l.text.strip()
		entry.log_entries.append((ltime, lcode, msg))
	return entry


class PowerTimer(Timer):
	def __init__(self):
		Timer.__init__(self)

		self.Filename = Directories.resolveFilename(Directories.SCOPE_CONFIG, "pm_timers.xml")

		try:
			self.loadTimer()
		except IOError:
			print("unable to load timers from file!")

	def doActivate(self, w, dosave=True):
		# when activating a timer which has already passed,
		# simply abort the timer. don't run trough all the stages.
		if w.shouldSkip():
			w.state = PowerTimerEntry.StateEnded
		else:
			# when active returns true, this means "accepted".
			# otherwise, the current state is kept.
			# the timer entry itself will fix up the delay then.
			if w.activate():
				w.state += 1

		try:
			self.timer_list.remove(w)
		except:
			print('[PowerManager]: Remove list failed')

		# did this timer reached the last state?
		if w.state < PowerTimerEntry.StateEnded:
			# no, sort it into active list
			insort(self.timer_list, w)
		else:
			# yes. Process repeated, and re-add.
			if w.repeated:
				# If we have saved original begin/end times for a backed off timer
				# restore those values now
				if hasattr(w, "real_begin"):
					w.begin = w.real_begin
					w.end = w.real_end
					# Now remove the temporary holding attributes...
					del w.real_begin
					del w.real_end
				w.processRepeated()
				w.state = PowerTimerEntry.StateWaiting
				self.addTimerEntry(w)
			else:
				insort(self.processed_timers, w)

		# Remove old timers as set in config (from RecordTimer settings...)
		# Pass in whether this is an AutosleepRepeat timer.
		self.cleanupLogs(config.recording.keep_timers.value, config.recording.keep_finished_timer_logs.value, (str(w.autosleeprepeat) == "repeated"))
		self.stateChanged(w)
		if dosave:
			self.saveTimer()

	def loadTimer(self):
		# TODO: PATH!
		if not Directories.fileExists(self.Filename):
			return

		root = Directories.fileReadXML(self.Filename, "<timers />")

		# put out a message when at least one timer overlaps
		checkit = True
		for timer in root.findall("timer"):
			newTimer = createTimer(timer)
			if (self.record(newTimer, True, dosave=False) is not None) and (checkit == True):
				from Tools.Notifications import AddPopup
				from Screens.MessageBox import MessageBox
				AddPopup(_("Timer overlap in pm_timers.xml detected!\nPlease recheck it!"), type=MessageBox.TYPE_ERROR, timeout=0, id="TimerLoadFailed")
				checkit = False  # at moment it is enough when the message is displayed one time

	def saveTimer(self):
		timerTypes = {
			TIMERTYPE.WAKEUP: "wakeup",
			TIMERTYPE.WAKEUPTOSTANDBY: "wakeuptostandby",
			TIMERTYPE.AUTOSTANDBY: "autostandby",
			TIMERTYPE.AUTODEEPSTANDBY: "autodeepstandby",
			TIMERTYPE.STANDBY: "standby",
			TIMERTYPE.DEEPSTANDBY: "deepstandby",
			TIMERTYPE.REBOOT: "reboot",
			TIMERTYPE.RESTART: "restart"
		}
		afterEvents = {
			AFTEREVENT.NONE: "nothing",
			AFTEREVENT.WAKEUPTOSTANDBY: "wakeuptostandby",
			AFTEREVENT.STANDBY: "standby",
			AFTEREVENT.DEEPSTANDBY: "deepstandby"
		}

		list = ['<?xml version="1.0" ?>\n<timers>\n']
		for timer in self.timer_list + self.processed_timers:
			if timer.dontSave:
				continue
			list.append('<timer'
						' timertype="%s"'
						' begin="%d"'
						' end="%d"'
						' repeated="%d"'
						' afterevent="%s"'
						' disabled="%d"'
						' autosleepinstandbyonly="%s"'
						' autosleepdelay="%s"'
						' autosleeprepeat="%s"' % (
						timerTypes[timer.timerType],
						int(timer.begin),
						int(timer.end),
						int(timer.repeated),
						afterEvents[timer.afterEvent],
						int(timer.disabled),
						timer.autosleepinstandbyonly,
						timer.autosleepdelay,
						timer.autosleeprepeat))

			if len(timer.log_entries) == 0:
				list.append('/>\n')
			else:
				for log_time, code, msg in timer.log_entries:
					list.append('>\n<log code="%d" time="%d">%s</log' % (code, log_time, stringToXML(msg)))
				list.append('>\n</timer>\n')

		list.append('</timers>\n')

		file = open(self.Filename + ".writing", "w")
		file.writelines(list)
		file.flush()

		os.fsync(file.fileno())
		file.close()
		os.rename(self.Filename + ".writing", self.Filename)

	def getNextZapTime(self):
		now = time()
		for timer in self.timer_list:
			if timer.begin < now:
				continue
			return timer.begin
		return -1

	def getNextPowerManagerTimeOld(self):
		now = time()
		for timer in self.timer_list:
			if timer.timerType != TIMERTYPE.AUTOSTANDBY and timer.timerType != TIMERTYPE.AUTODEEPSTANDBY:
				next_act = timer.getNextWakeup()
				if next_act < now:
					continue
				return next_act
		return -1

	def getNextPowerManagerTime(self):
		nextrectime = self.getNextPowerManagerTimeOld()
		faketime = time() + 300
		if config.timeshift.isRecording.value:
			if 0 < nextrectime < faketime:
				return nextrectime
			else:
				return faketime
		else:
			return nextrectime

	def isNextPowerManagerAfterEventActionAuto(self):
		now = time()
		t = None
		for timer in self.timer_list:
			if timer.timerType == TIMERTYPE.WAKEUPTOSTANDBY or timer.afterEvent == AFTEREVENT.WAKEUPTOSTANDBY:
				return True
		return False

	def record(self, entry, ignoreTSC=False, dosave=True):		#wird von loadTimer mit dosave=False aufgerufen
		entry.timeChanged()
		print("[PowerTimer]", str(entry))
		entry.Timer = self
		self.addTimerEntry(entry)
		if dosave:
			self.saveTimer()
		return None

	def removeEntry(self, entry):
		print("[PowerTimer] Remove", str(entry))

		# avoid re-enqueuing
		entry.repeated = False

		# abort timer.
		# this sets the end time to current time, so timer will be stopped.
		entry.autoincrease = False
		entry.abort()

		if entry.state != entry.StateEnded:
			self.timeChanged(entry)

# 		print "state: ", entry.state
# 		print "in processed: ", entry in self.processed_timers
# 		print "in running: ", entry in self.timer_list
		# disable timer first
		if entry.state != 3:
			entry.disable()
		# autoincrease instanttimer if possible
		if not entry.dontSave:
			for x in self.timer_list:
				if x.setAutoincreaseEnd():
					self.timeChanged(x)
		# now the timer should be in the processed_timers list. remove it from there.
		if entry in self.processed_timers:
			self.processed_timers.remove(entry)
		self.saveTimer()

	def shutdown(self):
		self.saveTimer()
