import locale
import os
import skin
from time import time
from boxbranding import getBrandOEM, getDisplayType

from enigma import eDVBDB, eEPGCache, setTunerTypePriorityOrder, setPreferredTuner, setSpinnerOnOff, setEnableTtCachingOnOff, eEnv, Misc_Options, eBackgroundFileEraser, eServiceEvent, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_HALIGN_CENTER, RT_VALIGN_CENTER, RT_WRAP

from Components.Harddisk import harddiskmanager
from Components.config import config, ConfigBoolean, ConfigClock, ConfigDictionarySet, ConfigDirectory, ConfigInteger, ConfigIP, ConfigLocations, ConfigNumber, ConfigPassword, ConfigSelection, ConfigSelectionNumber, ConfigSet, ConfigSlider, ConfigSubsection, ConfigText, ConfigYesNo, NoSave
from Tools.camcontrol import CamControl
from Tools.Directories import resolveFilename, SCOPE_HDD, SCOPE_TIMESHIFT, defaultRecordingLocation
from Components.NimManager import nimmanager
from Components.ServiceList import refreshServiceList
from Components.SystemInfo import SystemInfo
from Tools.HardwareInfo import HardwareInfo

# A raw writer for config changes to be read by the logger without
# getting a time-stamp prepended.
# stderr expect unicode, not str, so we decode as utf-8
#
import io


def raw_stderr_print(text):
	with io.open(2, mode="wt", closefd=False) as myerr:
		myerr.write(text)


originalAudioTracks = "orj dos ory org esl qaa qaf und mis mul ORY ORJ Audio_ORJ oth"
visuallyImpairedCommentary = "NAR qad"


def InitUsageConfig():
	config.version = ConfigNumber(default=0)
	if getBrandOEM() in ('vuplus', 'ini'):
		config.misc.remotecontrol_text_support = ConfigYesNo(default=True)
	else:
		config.misc.remotecontrol_text_support = ConfigYesNo(default=False)

	config.misc.usegstplaybin3 = ConfigYesNo(default=False)

	config.usage = ConfigSubsection()
	config.usage.subnetwork = ConfigYesNo(default=True)
	config.usage.subnetwork_cable = ConfigYesNo(default=True)
	config.usage.subnetwork_terrestrial = ConfigYesNo(default=True)
	config.usage.showdish = ConfigSelection(default="flashing", choices=[("flashing", _("Flashing")), ("normal", _("Not Flashing")), ("off", _("Off"))])
	showrotorpositionChoicesUpdate()
	config.usage.multibouquet = ConfigYesNo(default=True)
	config.usage.maxchannelnumlen = ConfigSelection(default="4", choices=[("3", _("3")), ("4", _("4")), ("5", _("5")), ("6", _("6"))])
	config.usage.alternative_number_mode = ConfigYesNo(default=False)

	def alternativeNumberModeChange(configElement):
		eDVBDB.getInstance().setNumberingMode(configElement.value)
		refreshServiceList()
	config.usage.alternative_number_mode.addNotifier(alternativeNumberModeChange)

	config.usage.servicelist_twolines = ConfigSelection(default="0", choices=[("0", _("None")), ("1", _("two lines")), ("2", _("two lines and next event"))])
	config.usage.servicelist_twolines.addNotifier(refreshServiceList)

	config.usage.hide_number_markers = ConfigYesNo(default=True)
	config.usage.hide_number_markers.addNotifier(refreshServiceList)

	config.usage.servicetype_icon_mode = ConfigSelection(default="0", choices=[("0", _("None")), ("1", _("Left from servicename")), ("2", _("Right from servicename"))])
	config.usage.servicetype_icon_mode.addNotifier(refreshServiceList)
	config.usage.crypto_icon_mode = ConfigSelection(default="0", choices=[("0", _("None")), ("1", _("Left from servicename")), ("2", _("Right from servicename"))])
	config.usage.crypto_icon_mode.addNotifier(refreshServiceList)
	config.usage.record_indicator_mode = ConfigSelection(default="3", choices=[("0", _("None")), ("1", _("Left from servicename")), ("2", _("Right from servicename")), ("3", _("Red colored"))])
	config.usage.record_indicator_mode.addNotifier(refreshServiceList)

	choicelist = [("-1", _("Disable"))]
	for i in range(0, 1300, 25):
		choicelist.append((str(i), ngettext("%d pixel wide", "%d pixels wide", i) % i))
	config.usage.servicelist_column = ConfigSelection(default="-1", choices=choicelist)
	config.usage.servicelist_column.addNotifier(refreshServiceList)

	config.usage.service_icon_enable = ConfigYesNo(default=False)
	config.usage.service_icon_enable.addNotifier(refreshServiceList)
	config.usage.servicelist_cursor_behavior = ConfigSelection(default="keep", choices=[
		("standard", _("Standard")),
		("keep", _("Keep service")),
		("reverseB", _("Reverse bouquet buttons")),
		("keep reverseB", _("Keep service") + " + " + _("Reverse bouquet buttons"))])

	config.usage.multiepg_ask_bouquet = ConfigYesNo(default=False)

	config.usage.panicbutton = ConfigYesNo(default=True)
	config.usage.quickzap_bouquet_change = ConfigYesNo(default=False)
	config.usage.e1like_radio_mode = ConfigYesNo(default=True)

	choicelist = [("0", _("No timeout"))] + \
		[(str(i), ngettext("%d second", "%d seconds", i) % i) for i in range(1, 21)]
	config.usage.infobar_timeout = ConfigSelection(default="5", choices=choicelist)
	config.usage.show_infobar_do_dimming = ConfigYesNo(default=False)
	config.usage.show_infobar_dimming_speed = ConfigSelectionNumber(min=1, max=40, stepwidth=1, default=40, wraparound=True)
	config.usage.show_infobar_on_zap = ConfigYesNo(default=True)
	config.usage.show_infobar_on_skip = ConfigYesNo(default=True)
	config.usage.show_infobar_on_event_change = ConfigYesNo(default=False)
	config.usage.show_infobar_channel_number = ConfigYesNo(default=False)
	choicelist = [("none", _("None")), ("0", _("No timeout"))] + \
		[(str(i), ngettext("%d second", "%d seconds", i) % i) for i in [3, 5, 7, 10, 15, 20, 30, 60]] + \
		[("EPG", _("EPG")), ("INFOBAREPG", _("InfoBar EPG"))]
	config.usage.show_second_infobar = ConfigSelection(default="5", choices=choicelist)

	def showsecondinfobarChanged(configElement):
		if config.usage.show_second_infobar.value != "INFOBAREPG":
			SystemInfo["InfoBarEpg"] = True
		else:
			SystemInfo["InfoBarEpg"] = False
	config.usage.show_second_infobar.addNotifier(showsecondinfobarChanged)

	try:
		SystemInfo["SecondInfoBarSimple"] = skin.parameters.get("SecondInfoBarSimple", 0) > 0
	except Exception as err:
		print("[UsageConfig] Error loading 'SecondInfoBarSimple' skin parameter! (%s)" % err)
		SystemInfo["SecondInfoBarSimple"] = False
	config.usage.second_infobar_simple = ConfigBoolean(descriptions={False: _("Standard"), True: _("Simple")}, graphic=False)

	config.usage.infobar_frontend_source = ConfigSelection(default="tuner", choices=[("settings", _("Settings")), ("tuner", _("Tuner"))])

	config.usage.show_picon_bkgrn = ConfigSelection(default="transparent", choices=[("none", _("Disabled")), ("transparent", _("Transparent")), ("blue", _("Blue")), ("red", _("Red")), ("black", _("Black")), ("white", _("White")), ("lightgrey", _("Light Grey")), ("grey", _("Grey"))])
	config.usage.show_genre_info = ConfigYesNo(default=False)
	config.usage.menu_style = ConfigSelection(default="standard", choices=[("standard", _("Standard")), ("horizontal", _("Horizontal"))])
	config.usage.menu_sort_weight = ConfigDictionarySet(default={"mainmenu": {"submenu": {}}})
	config.usage.menu_sort_mode = ConfigSelection(default="default", choices=[("a_z", _("alphabetical")), ("default", _("Default")), ("user", _("user defined")), ("user_hidden", _("user defined hidden"))])
	config.usage.menu_show_numbers = ConfigYesNo(default=False)
	config.usage.showScreenPath = ConfigSelection(default="small", choices=[("off", _("None")), ("small", _("Small")), ("large", _("Large"))])
	# The following code is to be short lived and exists to transition
	# settings from the old config.usage.show_menupath to the new
	# config.usage.showScreenPath as this is the value to now shared
	# by all images.  Thise code will transition the setting and then
	# remove the old entry from user's settings files.
	config.usage.show_menupath = ConfigSelection(default="small", choices=[("off", _("None")), ("small", _("Small")), ("large", _("Large"))])
	if config.usage.show_menupath.value != config.usage.show_menupath.default:
		config.usage.showScreenPath.value = config.usage.show_menupath.value
		config.usage.show_menupath.value = config.usage.show_menupath.default
		config.usage.save()
		print("[UserConfig] DEBUG: The 'show_menupath' setting of '%s' has been transferred to 'showScreenPath'." % config.usage.showScreenPath.value)
	# End of temporary code.
	config.usage.show_spinner = ConfigYesNo(default=True)
	config.usage.enable_tt_caching = ConfigYesNo(default=True)
	config.usage.sort_settings = ConfigYesNo(default=False)
	config.usage.sort_pluginlist = ConfigYesNo(default=True)
	config.usage.movieplayer_pvrstate = ConfigYesNo(default=True)

	config.usage.setupShowDefault = ConfigSelection(default="spaces", choices=[
		("", _("Don't show default")),
		("spaces", _("Show default after description")),
		("newline", _("Show default on new line"))
	])

	choicelist = []
	for i in (10, 30):
		choicelist.append((str(i), ngettext("%d second", "%d seconds", i) % i))
	for i in (60, 120, 300, 600, 1200, 1800):
		m = i // 60
		choicelist.append((str(i), ngettext("%d minute", "%d minutes", m) % m))
	for i in (3600, 7200, 14400):
		h = i // 3600
		choicelist.append((str(i), ngettext("%d hour", "%d hours", h) % h))
	config.usage.hdd_standby = ConfigSelection(default="300", choices=[("0", _("No standby"))] + choicelist)
	config.usage.output_12V = ConfigSelection(default="do not change", choices=[
		("do not change", _("Do not change")), ("off", _("Off")), ("on", _("On"))])

	config.usage.pip_zero_button = ConfigSelection(default="standard", choices=[
		("standard", _("Standard")), ("swap", _("Swap PiP and main picture")),
		("swapstop", _("Move PiP to main picture")), ("stop", _("Stop PiP"))])
	config.usage.pip_hideOnExit = ConfigSelection(default="no", choices=[
		("no", _("No")), ("popup", _("With popup")), ("without popup", _("Without popup"))])
	choicelist = [("-1", _("Disabled")), ("0", _("No timeout"))]
	for i in [60, 300, 600, 900, 1800, 2700, 3600]:
		m = i // 60
		choicelist.append((str(i), ngettext("%d minute", "%d minutes", m) % m))
	config.usage.pip_last_service_timeout = ConfigSelection(default="0", choices=choicelist)

	if not os.path.exists(resolveFilename(SCOPE_HDD)):
		try:
			os.mkdir(resolveFilename(SCOPE_HDD), 0o755)
		except (IOError, OSError):
			pass
	defaultValue = resolveFilename(SCOPE_HDD)
	config.usage.default_path = ConfigSelection(default=defaultValue, choices=[(defaultValue, defaultValue)])
	config.usage.default_path.load()
	if config.usage.default_path.saved_value:
		savedValue = os.path.join(config.usage.default_path.saved_value, "")
		if savedValue and savedValue != defaultValue:
			config.usage.default_path.setChoices([(defaultValue, defaultValue), (savedValue, savedValue)], default=defaultValue)
			config.usage.default_path.value = savedValue
	config.usage.default_path.save()
	choiceList = [("<default>", "<default>"), ("<current>", "<current>"), ("<timer>", "<timer>")]
	config.usage.timer_path = ConfigSelection(default="<default>", choices=choiceList)
	config.usage.timer_path.load()
	if config.usage.timer_path.saved_value:
		savedValue = config.usage.timer_path.saved_value if config.usage.timer_path.saved_value.startswith("<") else os.path.join(config.usage.timer_path.saved_value, "")
		if savedValue and savedValue not in choiceList:
			config.usage.timer_path.setChoices(choiceList + [(savedValue, savedValue)], default="<default>")
			config.usage.timer_path.value = savedValue
	config.usage.timer_path.save()
	config.usage.instantrec_path = ConfigSelection(default="<default>", choices=choiceList)
	config.usage.instantrec_path.load()
	if config.usage.instantrec_path.saved_value:
		savedValue = config.usage.instantrec_path.saved_value if config.usage.instantrec_path.saved_value.startswith("<") else os.path.join(config.usage.instantrec_path.saved_value, "")
		if savedValue and savedValue not in choiceList:
			config.usage.instantrec_path.setChoices(choiceList + [(savedValue, savedValue)], default="<default>")
			config.usage.instantrec_path.value = savedValue
	config.usage.instantrec_path.save()
	if not os.path.exists(resolveFilename(SCOPE_TIMESHIFT)):
		try:
			os.mkdir(resolveFilename(SCOPE_TIMESHIFT), 0o755)
		except:
			pass
	defaultValue = resolveFilename(SCOPE_TIMESHIFT)
	config.usage.timeshift_path = ConfigSelection(default=defaultValue, choices=[(defaultValue, defaultValue)])
	config.usage.timeshift_path.load()
	if config.usage.timeshift_path.saved_value:
		savedValue = os.path.join(config.usage.timeshift_path.saved_value, "")
		if savedValue and savedValue != defaultValue:
			config.usage.timeshift_path.setChoices([(defaultValue, defaultValue), (savedValue, savedValue)], default=defaultValue)
			config.usage.timeshift_path.value = savedValue
	config.usage.timeshift_path.save()
	config.usage.allowed_timeshift_paths = ConfigLocations(default=[resolveFilename(SCOPE_TIMESHIFT)])
	config.usage.timeshift_skipreturntolive = ConfigYesNo(default=False)

	config.usage.trashsort_deltime = ConfigSelection(default="no", choices=[
		("no", _("no")),
		("show record time", _("Yes, show record time")),
		("show delete time", _("Yes, show delete time"))])
	config.usage.movielist_trashcan = ConfigYesNo(default=True)
	config.usage.movielist_trashcan_network_clean = ConfigYesNo(default=False)

	config.usage.movielist_trashcan_days = ConfigSelectionNumber(min=0, max=31, stepwidth=1, default=8, wraparound=True)
	config.usage.movielist_trashcan_reserve = ConfigNumber(default=40)
	config.usage.on_movie_start = ConfigSelection(default="ask yes", choices=[
		("ask yes", _("Ask user (with default as 'yes')")),
		("ask no", _("Ask user (with default as 'no')")),
		("resume", _("Resume from last position")),
		("beginning", _("Start from the beginning"))])
	config.usage.on_movie_stop = ConfigSelection(default="movielist", choices=[
		("ask", _("Ask user")), ("movielist", _("Return to movie list")), ("quit", _("Return to previous service"))])
	config.usage.on_movie_eof = ConfigSelection(default="movielist", choices=[
		("ask", _("Ask user")), ("movielist", _("Return to movie list")), ("quit", _("Return to previous service")), ("pause", _("Pause movie at end")), ("playlist", _("Play next (return to movie list)")),
		("playlistquit", _("Play next (return to previous service)")), ("loop", _("Continues play (loop)")), ("repeatcurrent", _("Repeat"))])
	config.usage.next_movie_msg = ConfigYesNo(default=True)
	config.usage.last_movie_played = ConfigText()
	config.usage.leave_movieplayer_onExit = ConfigSelection(default="no", choices=[
		("no", _("No")), ("popup", _("With popup")), ("without popup", _("Without popup")), ("stop", _("Behave like stop-button"))])

	config.usage.setup_level = ConfigSelection(default="expert", choices=[
		("simple", _("Simple")),
		("intermediate", _("Intermediate")),
		("expert", _("Expert"))])

	config.usage.help_sortorder = ConfigSelection(default="headings+alphabetic", choices=[
		("headings+alphabetic", _("Alphabetical under headings")),
		("flat+alphabetic", _("Flat alphabetical")),
		("flat+remotepos", _("Flat by position on remote")),
		("flat+remotegroups", _("Flat by key group on remote"))])

	config.usage.on_long_powerpress = ConfigSelection(default="show_menu", choices=[
		("show_menu", _("Show shutdown menu")),
		("shutdown", _("Immediate shutdown")),
		("standby", _("Standby"))])

	config.usage.on_short_powerpress = ConfigSelection(default="standby", choices=[
		("show_menu", _("Show shutdown menu")),
		("shutdown", _("Immediate shutdown")),
		("standby", _("Standby"))])

	choicelist = [("0", _("Disabled"))]
	for i in (5, 30, 60, 300, 600, 900, 1200, 1800, 2700, 3600):
		if i < 60:
			m = ngettext("%d second", "%d seconds", i) % i
		else:
			m = abs(i // 60)
			m = ngettext("%d minute", "%d minutes", m) % m
		choicelist.append(("%d" % i, m))
	config.usage.screen_saver = ConfigSelection(default="60", choices=choicelist)

	config.usage.check_timeshift = ConfigYesNo(default=True)

	config.usage.bootlogo_identify = ConfigYesNo(default=True)

	config.usage.alternatives_priority = ConfigSelection(default="0", choices=[
		("0", "DVB-S/-C/-T"),
		("1", "DVB-S/-T/-C"),
		("2", "DVB-C/-S/-T"),
		("3", "DVB-C/-T/-S"),
		("4", "DVB-T/-C/-S"),
		("5", "DVB-T/-S/-C"),
		("127", _("No priority"))])

	config.usage.remote_fallback_enabled = ConfigYesNo(default=False)
	config.usage.remote_fallback = ConfigText(default="", fixed_size=False)

	config.usage.task_warning = ConfigYesNo(default=True)

	config.usage.jobtaskextensions = ConfigYesNo(default=True)
	config.misc.disable_background_scan = ConfigYesNo(default=False)
	config.misc.use_ci_assignment = ConfigYesNo(default=False)

	choicelist = [("0", _("Disabled"))]
	for i in (10, 50, 100, 500, 1000, 2000):
		choicelist.append(("%d" % i, _("%d ms") % i))

	config.usage.http_startdelay = ConfigSelection(default="0", choices=choicelist)

	preferredTunerChoicesUpdate()

	config.usage.servicenum_fontsize = ConfigSelectionNumber(default=0, stepwidth=1, min=-8, max=10, wraparound=True)
	config.usage.servicename_fontsize = ConfigSelectionNumber(default=0, stepwidth=1, min=-8, max=10, wraparound=True)
	config.usage.serviceinfo_fontsize = ConfigSelectionNumber(default=0, stepwidth=1, min=-8, max=10, wraparound=True)
	choices = [(0, _("Use skin default"))] + [(i, _("%d") % i) for i in range(1, 41)]
	config.usage.serviceitems_per_page = ConfigSelection(default=0, choices=choices)
	config.usage.show_servicelist = ConfigYesNo(default=True)
	config.usage.servicelist_mode = ConfigSelection(default="standard", choices=[
		("standard", _("Standard")),
		("simple", _("Slim"))])
	config.usage.servicelistpreview_mode = ConfigYesNo(default=False)
	config.usage.tvradiobutton_mode = ConfigSelection(default="BouquetList", choices=[
					("ChannelList", _("Channel List")),
					("BouquetList", _("Bouquet List")),
					("MovieList", _("Movie List"))])
	config.usage.show_bouquetalways = ConfigYesNo(default=False)
	config.usage.show_event_progress_in_servicelist = ConfigSelection(default='barright', choices=[
		('barleft', _("Progress bar left")),
		('barright', _("Progress bar right")),
		('percleft', _("Percentage left")),
		('percright', _("Percentage right")),
		('no', _("No"))])
	config.usage.show_channel_numbers_in_servicelist = ConfigYesNo(default=True)
	config.usage.show_channel_jump_in_servicelist = ConfigSelection(default="alpha", choices=[
					("quick", _("Quick Actions")),
					("alpha", _("Alpha")),
					("number", _("Number"))])

	config.usage.show_event_progress_in_servicelist.addNotifier(refreshServiceList)
	config.usage.show_channel_numbers_in_servicelist.addNotifier(refreshServiceList)

	if SystemInfo["WakeOnLAN"]:
		def wakeOnLANChanged(configElement):
			if "fp" in SystemInfo["WakeOnLAN"]:
				open(SystemInfo["WakeOnLAN"], "w").write(configElement.value and "enable" or "disable")
			else:
				open(SystemInfo["WakeOnLAN"], "w").write(configElement.value and "on" or "off")
		config.usage.wakeOnLAN = ConfigYesNo(default=False)
		config.usage.wakeOnLAN.addNotifier(wakeOnLANChanged)

	#standby
	if getDisplayType() in ("textlcd7segment"):
		config.usage.blinking_display_clock_during_recording = ConfigSelection(default="Rec", choices=[
						("Rec", _("REC")),
						("RecBlink", _("Blinking REC")),
						("Nothing", _("Nothing"))])
	else:
		config.usage.blinking_display_clock_during_recording = ConfigYesNo(default=False)

	#in use
	if getDisplayType() in ("textlcd"):
		config.usage.blinking_rec_symbol_during_recording = ConfigSelection(default="Channel", choices=[
						("Rec", _("REC Symbol")),
						("RecBlink", _("Blinking REC Symbol")),
						("Channel", _("Channelname"))])
	if getDisplayType() in ("textlcd7segment"):
		config.usage.blinking_rec_symbol_during_recording = ConfigSelection(default="Rec", choices=[
						("Rec", _("REC")),
						("RecBlink", _("Blinking REC")),
						("Time", _("Time"))])
	else:
		config.usage.blinking_rec_symbol_during_recording = ConfigYesNo(default=True)

	if getDisplayType() in ("textlcd7segment"):
		config.usage.show_in_standby = ConfigSelection(default="time", choices=[
						("time", _("Time")),
						("nothing", _("Nothing"))])

	config.usage.show_message_when_recording_starts = ConfigYesNo(default=True)

	config.usage.load_length_of_movies_in_moviellist = ConfigYesNo(default=True)
	config.usage.show_icons_in_movielist = ConfigSelection(default='i', choices=[
		('o', _("Off")),
		('p', _("Progress")),
		('s', _("Small progress")),
		('i', _("Icons")),
	])
	config.usage.movielist_unseen = ConfigYesNo(default=True)
	config.usage.movielist_servicename_mode = ConfigSelection(default="", choices=[
		("", _("None")),
		("picon", _("Picon"))
	])
	config.usage.movielist_piconwidth = ConfigSelectionNumber(default=100, stepwidth=1, min=50, max=500, wraparound=True)

	config.usage.swap_snr_on_osd = ConfigYesNo(default=False)
	config.usage.swap_time_display_on_osd = ConfigSelection(default="0", choices=[("0", _("Skin Setting")), ("1", _("Mins")), ("2", _("Mins Secs")), ("3", _("Hours Mins")), ("4", _("Hours Mins Secs")), ("5", _("Percentage"))])
	config.usage.swap_media_time_display_on_osd = ConfigSelection(default="0", choices=[("0", _("Skin Setting")), ("1", _("Mins")), ("2", _("Mins Secs")), ("3", _("Hours Mins")), ("4", _("Hours Mins Secs")), ("5", _("Percentage"))])
	config.usage.swap_time_remaining_on_osd = ConfigSelection(default="0", choices=[("0", _("Remaining")), ("1", _("Elapsed")), ("2", _("Elapsed & Remaining")), ("3", _("Remaining & Elapsed"))])
	config.usage.elapsed_time_positive_osd = ConfigYesNo(default=False)
	config.usage.swap_time_display_on_vfd = ConfigSelection(default="0", choices=[("0", _("Skin Setting")), ("1", _("Mins")), ("2", _("Mins Secs")), ("3", _("Hours Mins")), ("4", _("Hours Mins Secs")), ("5", _("Percentage"))])
	config.usage.swap_media_time_display_on_vfd = ConfigSelection(default="0", choices=[("0", _("Skin Setting")), ("1", _("Mins")), ("2", _("Mins Secs")), ("3", _("Hours Mins")), ("4", _("Hours Mins Secs")), ("5", _("Percentage"))])
	config.usage.swap_time_remaining_on_vfd = ConfigSelection(default="0", choices=[("0", _("Remaining")), ("1", _("Elapsed")), ("2", _("Elapsed & Remaining")), ("3", _("Remaining & Elapsed"))])
	config.usage.elapsed_time_positive_vfd = ConfigYesNo(default=False)

	def SpinnerOnOffChanged(configElement):
		setSpinnerOnOff(int(configElement.value))
	config.usage.show_spinner.addNotifier(SpinnerOnOffChanged)

	def EnableTtCachingChanged(configElement):
		setEnableTtCachingOnOff(int(configElement.value))
	config.usage.enable_tt_caching.addNotifier(EnableTtCachingChanged)

	def TunerTypePriorityOrderChanged(configElement):
		setTunerTypePriorityOrder(int(configElement.value))
	config.usage.alternatives_priority.addNotifier(TunerTypePriorityOrderChanged, immediate_feedback=False)

	def PreferredTunerChanged(configElement):
		setPreferredTuner(int(configElement.value))
	config.usage.frontend_priority.addNotifier(PreferredTunerChanged)

	config.usage.hide_zap_errors = ConfigYesNo(default=True)
	config.usage.hide_ci_messages = ConfigYesNo(default=False)
	config.usage.show_cryptoinfo = ConfigSelection([("0", _("Off")), ("1", _("One line")), ("2", _("Two lines"))], "2")
	config.usage.show_eit_nownext = ConfigYesNo(default=True)
	config.usage.show_vcr_scart = ConfigYesNo(default=False)
	config.usage.pic_resolution = ConfigSelection(default=None, choices=[(None, _("Same resolution as skin")), ("(720, 576)", "720x576"), ("(1280, 720)", "1280x720"), ("(1920, 1080)", "1920x1080")])

	config.usage.date = ConfigSubsection()
	config.usage.date.enabled = NoSave(ConfigBoolean(default=False))
	config.usage.date.enabled_display = NoSave(ConfigBoolean(default=False))
	config.usage.date.dateFormatAbout = ConfigSelection(default="%(day)s-%(month)s-%(year)s", choices=[("%(day)s-%(month)s-%(year)s", _("DD-MM-YYYY")), ("%(month)s-%(day)s-%(year)s", _("MM-DD-YYYY")), ("%(year)s-%(month)s-%(day)s", _("YYYY-MM-DD"))])
	config.usage.time = ConfigSubsection()
	config.usage.time.enabled = NoSave(ConfigBoolean(default=False))
	config.usage.time.disabled = NoSave(ConfigBoolean(default=True))
	config.usage.time.enabled_display = NoSave(ConfigBoolean(default=False))
	config.usage.time.wide = NoSave(ConfigBoolean(default=False))
	config.usage.time.wide_display = NoSave(ConfigBoolean(default=False))

	# TRANSLATORS: full date representation dayname daynum monthname year in strftime() format! See 'man strftime'
	config.usage.date.dayfull = ConfigSelection(default=_("%A %-d %B %Y"), choices=[
		(_("%A %d %B %Y"), _("Dayname DD Month Year")),
		(_("%A %d. %B %Y"), _("Dayname DD. Month Year")),
		(_("%A %-d %B %Y"), _("Dayname D Month Year")),
		(_("%A %-d. %B %Y"), _("Dayname D. Month Year")),
		(_("%A %d-%B-%Y"), _("Dayname DD-Month-Year")),
		(_("%A %-d-%B-%Y"), _("Dayname D-Month-Year")),
		(_("%A %d/%m/%Y"), _("Dayname DD/MM/Year")),
		(_("%A %d.%m.%Y"), _("Dayname DD.MM.Year")),
		(_("%A %-d/%m/%Y"), _("Dayname D/MM/Year")),
		(_("%A %-d.%m.%Y"), _("Dayname D.MM.Year")),
		(_("%A %d/%-m/%Y"), _("Dayname DD/M/Year")),
		(_("%A %d.%-m.%Y"), _("Dayname DD.M.Year")),
		(_("%A %-d/%-m/%Y"), _("Dayname D/M/Year")),
		(_("%A %-d.%-m.%Y"), _("Dayname D.M.Year")),
		(_("%A %B %d %Y"), _("Dayname Month DD Year")),
		(_("%A %B %-d %Y"), _("Dayname Month D Year")),
		(_("%A %B-%d-%Y"), _("Dayname Month-DD-Year")),
		(_("%A %B-%-d-%Y"), _("Dayname Month-D-Year")),
		(_("%A %m/%d/%Y"), _("Dayname MM/DD/Year")),
		(_("%A %-m/%d/%Y"), _("Dayname M/DD/Year")),
		(_("%A %m/%-d/%Y"), _("Dayname MM/D/Year")),
		(_("%A %-m/%-d/%Y"), _("Dayname M/D/Year")),
		(_("%A %Y %B %d"), _("Dayname Year Month DD")),
		(_("%A %Y %B %-d"), _("Dayname Year Month D")),
		(_("%A %Y-%B-%d"), _("Dayname Year-Month-DD")),
		(_("%A %Y-%B-%-d"), _("Dayname Year-Month-D")),
		(_("%A %Y/%m/%d"), _("Dayname Year/MM/DD")),
		(_("%A %Y/%m/%-d"), _("Dayname Year/MM/D")),
		(_("%A %Y/%-m/%d"), _("Dayname Year/M/DD")),
		(_("%A %Y/%-m/%-d"), _("Dayname Year/M/D"))
	])

	# TRANSLATORS: long date representation short dayname daynum monthname year in strftime() format! See 'man strftime'
	config.usage.date.shortdayfull = ConfigText(default=_("%a %-d %B %Y"))

	# TRANSLATORS: long date representation short dayname daynum short monthname year in strftime() format! See 'man strftime'
	config.usage.date.daylong = ConfigText(default=_("%a %-d %b %Y"))

	# TRANSLATORS: short date representation dayname daynum short monthname in strftime() format! See 'man strftime'
	config.usage.date.dayshortfull = ConfigText(default=_("%A %-d %B"))

	# TRANSLATORS: short date representation short dayname daynum short monthname in strftime() format! See 'man strftime'
	config.usage.date.dayshort = ConfigText(default=_("%a %-d %b"))

	# TRANSLATORS: small date representation short dayname daynum in strftime() format! See 'man strftime'
	config.usage.date.daysmall = ConfigText(default=_("%a %-d"))

	# TRANSLATORS: full date representation daynum monthname year in strftime() format! See 'man strftime'
	config.usage.date.full = ConfigText(default=_("%-d %B %Y"))

	# TRANSLATORS: long date representation daynum short monthname year in strftime() format! See 'man strftime'
	config.usage.date.long = ConfigText(default=_("%-d %b %Y"))

	# TRANSLATORS: small date representation daynum short monthname in strftime() format! See 'man strftime'
	config.usage.date.short = ConfigText(default=_("%-d %b"))

	def setDateStyles(configElement):
		dateStyles = {
			# dayfull            shortdayfull      daylong           dayshortfull   dayshort       daysmall    full           long           short
			_("%A %d %B %Y"): (_("%a %d %B %Y"), _("%a %d %b %Y"), _("%A %d %B"), _("%a %d %b"), _("%a %d"), _("%d %B %Y"), _("%d %b %Y"), _("%d %b")),
			_("%A %d. %B %Y"): (_("%a %d. %B %Y"), _("%a %d. %b %Y"), _("%A %d. %B"), _("%a %d. %b"), _("%a %d"), _("%d. %B %Y"), _("%d. %b %Y"), _("%d. %b")),
			_("%A %-d %B %Y"): (_("%a %-d %B %Y"), _("%a %-d %b %Y"), _("%A %-d %B"), _("%a %-d %b"), _("%a %-d"), _("%-d %B %Y"), _("%-d %b %Y"), _("%-d %b")),
			_("%A %-d. %B %Y"): (_("%a %-d. %B %Y"), _("%a %-d. %b %Y"), _("%A %-d. %B"), _("%a %-d. %b"), _("%a %-d"), _("%-d. %B %Y"), _("%-d. %b %Y"), _("%-d. %b")),
			_("%A %d-%B-%Y"): (_("%a %d-%B-%Y"), _("%a %d-%b-%Y"), _("%A %d-%B"), _("%a %d-%b"), _("%a %d"), _("%d-%B-%Y"), _("%d-%b-%Y"), _("%d-%b")),
			_("%A %-d-%B-%Y"): (_("%a %-d-%B-%Y"), _("%a %-d-%b-%Y"), _("%A %-d-%B"), _("%a %-d-%b"), _("%a %-d"), _("%-d-%B-%Y"), _("%-d-%b-%Y"), _("%-d-%b")),
			_("%A %d/%m/%Y"): (_("%a %d/%m/%Y"), _("%a %d/%m/%Y"), _("%A %d/%m"), _("%a %d/%m"), _("%a %d"), _("%d/%m/%Y"), _("%d/%m/%Y"), _("%d/%m")),
			_("%A %d.%m.%Y"): (_("%a %d.%m.%Y"), _("%a %d.%m.%Y"), _("%A %d.%m"), _("%a %d.%m"), _("%a %d"), _("%d.%m.%Y"), _("%d.%m.%Y"), _("%d.%m")),
			_("%A %-d/%m/%Y"): (_("%a %-d/%m/%Y"), _("%a %-d/%m/%Y"), _("%A %-d/%m"), _("%a %-d/%m"), _("%a %-d"), _("%-d/%m/%Y"), _("%-d/%m/%Y"), _("%-d/%m")),
			_("%A %-d.%m.%Y"): (_("%a %-d.%m.%Y"), _("%a %-d.%m.%Y"), _("%A %-d.%m"), _("%a %-d.%m"), _("%a %-d"), _("%-d.%m.%Y"), _("%-d.%m.%Y"), _("%-d.%m")),
			_("%A %d/%-m/%Y"): (_("%a %d/%-m/%Y"), _("%a %d/%-m/%Y"), _("%A %d/%-m"), _("%a %d/%-m"), _("%a %d"), _("%d/%-m/%Y"), _("%d/%-m/%Y"), _("%d/%-m")),
			_("%A %d.%-m.%Y"): (_("%a %d.%-m.%Y"), _("%a %d.%-m.%Y"), _("%A %d.%-m"), _("%a %d.%-m"), _("%a %d"), _("%d.%-m.%Y"), _("%d.%-m.%Y"), _("%d.%-m")),
			_("%A %-d/%-m/%Y"): (_("%a %-d/%-m/%Y"), _("%a %-d/%-m/%Y"), _("%A %-d/%-m"), _("%a %-d/%-m"), _("%a %-d"), _("%-d/%-m/%Y"), _("%-d/%-m/%Y"), _("%-d/%-m")),
			_("%A %-d.%-m.%Y"): (_("%a %-d.%-m.%Y"), _("%a %-d.%-m.%Y"), _("%A %-d.%-m"), _("%a %-d.%-m"), _("%a %-d"), _("%-d.%-m.%Y"), _("%-d.%-m.%Y"), _("%-d.%-m")),
			_("%A %B %d %Y"): (_("%a %B %d %Y"), _("%a %b %d %Y"), _("%A %B %d"), _("%a %b %d"), _("%a %d"), _("%B %d %Y"), _("%b %d %Y"), _("%b %d")),
			_("%A %B %-d %Y"): (_("%a %B %-d %Y"), _("%a %b %-d %Y"), _("%A %B %-d"), _("%a %b %-d"), _("%a %-d"), _("%B %-d %Y"), _("%b %-d %Y"), _("%b %-d")),
			_("%A %B-%d-%Y"): (_("%a %B-%d-%Y"), _("%a %b-%d-%Y"), _("%A %B-%d"), _("%a %b-%d"), _("%a %d"), _("%B-%d-%Y"), _("%b-%d-%Y"), _("%b-%d")),
			_("%A %B-%-d-%Y"): (_("%a %B-%-d-%Y"), _("%a %b-%-d-%Y"), _("%A %B-%-d"), _("%a %b-%-d"), _("%a %-d"), _("%B-%-d-%Y"), _("%b-%-d-%Y"), _("%b-%-d")),
			_("%A %m/%d/%Y"): (_("%a %m/%d/%Y"), _("%a %m/%d/%Y"), _("%A %m/%d"), _("%a %m/%d"), _("%a %d"), _("%m/%d/%Y"), _("%m/%d/%Y"), _("%m/%d")),
			_("%A %-m/%d/%Y"): (_("%a %-m/%d/%Y"), _("%a %-m/%d/%Y"), _("%A %-m/%d"), _("%a %-m/%d"), _("%a %d"), _("%-m/%d/%Y"), _("%-m/%d/%Y"), _("%-m/%d")),
			_("%A %m/%-d/%Y"): (_("%a %m/%-d/%Y"), _("%a %m/%-d/%Y"), _("%A %m/%-d"), _("%a %m/%-d"), _("%a %-d"), _("%m/%-d/%Y"), _("%m/%-d/%Y"), _("%m/%-d")),
			_("%A %-m/%-d/%Y"): (_("%a %-m/%-d/%Y"), _("%a %-m/%-d/%Y"), _("%A %-m/%-d"), _("%a %-m/%-d"), _("%a %-d"), _("%-m/%-d/%Y"), _("%-m/%-d/%Y"), _("%-m/%-d")),
			_("%A %Y %B %d"): (_("%a %Y %B %d"), _("%a %Y %b %d"), _("%A %B %d"), _("%a %b %d"), _("%a %d"), _("%Y %B %d"), _("%Y %b %d"), _("%b %d")),
			_("%A %Y %B %-d"): (_("%a %Y %B %-d"), _("%a %Y %b %-d"), _("%A %B %-d"), _("%a %b %-d"), _("%a %-d"), _("%Y %B %-d"), _("%Y %b %-d"), _("%b %-d")),
			_("%A %Y-%B-%d"): (_("%a %Y-%B-%d"), _("%a %Y-%b-%d"), _("%A %B-%d"), _("%a %b-%d"), _("%a %d"), _("%Y-%B-%d"), _("%Y-%b-%d"), _("%b-%d")),
			_("%A %Y-%B-%-d"): (_("%a %Y-%B-%-d"), _("%a %Y-%b-%-d"), _("%A %B-%-d"), _("%a %b-%-d"), _("%a %-d"), _("%Y-%B-%-d"), _("%Y-%b-%-d"), _("%b-%-d")),
			_("%A %Y/%m/%d"): (_("%a %Y/%m/%d"), _("%a %Y/%m/%d"), _("%A %m/%d"), _("%a %m/%d"), _("%a %d"), _("%Y/%m/%d"), _("%Y/%m/%d"), _("%m/%d")),
			_("%A %Y/%m/%-d"): (_("%a %Y/%m/%-d"), _("%a %Y/%m/%-d"), _("%A %m/%-d"), _("%a %m/%-d"), _("%a %-d"), _("%Y/%m/%-d"), _("%Y/%m/%-d"), _("%m/%-d")),
			_("%A %Y/%-m/%d"): (_("%a %Y/%-m/%d"), _("%a %Y/%-m/%d"), _("%A %-m/%d"), _("%a %-m/%d"), _("%a %d"), _("%Y/%-m/%d"), _("%Y/%-m/%d"), _("%-m/%d")),
			_("%A %Y/%-m/%-d"): (_("%a %Y/%-m/%-d"), _("%a %Y/%-m/%-d"), _("%A %-m/%-d"), _("%a %-m/%-d"), _("%a %-d"), _("%Y/%-m/%-d"), _("%Y/%-m/%-d"), _("%-m/%-d"))
		}
		style = dateStyles.get(configElement.value, ((_("Invalid")) * 8))
		config.usage.date.shortdayfull.value = style[0]
		config.usage.date.shortdayfull.save()
		config.usage.date.daylong.value = style[1]
		config.usage.date.daylong.save()
		config.usage.date.dayshortfull.value = style[2]
		config.usage.date.dayshortfull.save()
		config.usage.date.dayshort.value = style[3]
		config.usage.date.dayshort.save()
		config.usage.date.daysmall.value = style[4]
		config.usage.date.daysmall.save()
		config.usage.date.full.value = style[5]
		config.usage.date.full.save()
		config.usage.date.long.value = style[6]
		config.usage.date.long.save()
		config.usage.date.short.value = style[7]
		config.usage.date.short.save()

	config.usage.date.dayfull.addNotifier(setDateStyles)

	# TRANSLATORS: full time representation hour:minute:seconds
	if locale.nl_langinfo(locale.AM_STR) and locale.nl_langinfo(locale.PM_STR):
		config.usage.time.long = ConfigSelection(default=_("%T"), choices=[
			(_("%T"), _("HH:mm:ss")),
			(_("%-H:%M:%S"), _("H:mm:ss")),
			(_("%I:%M:%S%^p"), _("hh:mm:ssAM/PM")),
			(_("%-I:%M:%S%^p"), _("h:mm:ssAM/PM")),
			(_("%I:%M:%S%P"), _("hh:mm:ssam/pm")),
			(_("%-I:%M:%S%P"), _("h:mm:ssam/pm")),
			(_("%I:%M:%S"), _("hh:mm:ss")),
			(_("%-I:%M:%S"), _("h:mm:ss"))
		])
	else:
		config.usage.time.long = ConfigSelection(default=_("%T"), choices=[
			(_("%T"), _("HH:mm:ss")),
			(_("%-H:%M:%S"), _("H:mm:ss")),
			(_("%I:%M:%S"), _("hh:mm:ss")),
			(_("%-I:%M:%S"), _("h:mm:ss"))
		])

	# TRANSLATORS: time representation hour:minute:seconds for 24 hour clock or 12 hour clock without AM/PM and hour:minute for 12 hour clocks with AM/PM
	config.usage.time.mixed = ConfigText(default=_("%T"))

	# TRANSLATORS: short time representation hour:minute (Same as "Default")
	config.usage.time.short = ConfigText(default=_("%R"))

	def setTimeStyles(configElement):
		timeStyles = {
			# long      mixed    short
			_("%T"): (_("%T"), _("%R")),
			_("%-H:%M:%S"): (_("%-H:%M:%S"), _("%-H:%M")),
			_("%I:%M:%S%^p"): (_("%I:%M%^p"), _("%I:%M%^p")),
			_("%-I:%M:%S%^p"): (_("%-I:%M%^p"), _("%-I:%M%^p")),
			_("%I:%M:%S%P"): (_("%I:%M%P"), _("%I:%M%P")),
			_("%-I:%M:%S%P"): (_("%-I:%M%P"), _("%-I:%M%P")),
			_("%I:%M:%S"): (_("%I:%M:%S"), _("%I:%M")),
			_("%-I:%M:%S"): (_("%-I:%M:%S"), _("%-I:%M"))
		}
		style = timeStyles.get(configElement.value, ((_("Invalid")) * 2))
		config.usage.time.mixed.value = style[0]
		config.usage.time.mixed.save()
		config.usage.time.short.value = style[1]
		config.usage.time.short.save()
		config.usage.time.wide.value = style[1].endswith(("P", "p"))

	config.usage.time.long.addNotifier(setTimeStyles)

	try:
		dateEnabled, timeEnabled = skin.parameters.get("AllowUserDatesAndTimes", (0, 0))
	except Exception as error:
		print("[UsageConfig] Error loading 'AllowUserDatesAndTimes' skin parameter! (%s)" % error)
		dateEnabled, timeEnabled = (0, 0)
	if dateEnabled:
		config.usage.date.enabled.value = True
	else:
		config.usage.date.enabled.value = False
		config.usage.date.dayfull.value = config.usage.date.dayfull.default
	if timeEnabled:
		config.usage.time.enabled.value = True
		config.usage.time.disabled.value = not config.usage.time.enabled.value
	else:
		config.usage.time.enabled.value = False
		config.usage.time.disabled.value = not config.usage.time.enabled.value
		config.usage.time.long.value = config.usage.time.long.default

	# TRANSLATORS: compact date representation (for VFD) daynum short monthname in strftime() format! See 'man strftime'
	config.usage.date.display = ConfigSelection(default=_("%-d %b"), choices=[
		("", _("Hidden / Blank")),
		(_("%d %b"), _("Day DD Mon")),
		(_("%-d %b"), _("Day D Mon")),
		(_("%d-%b"), _("Day DD-Mon")),
		(_("%-d-%b"), _("Day D-Mon")),
		(_("%d/%m"), _("Day DD/MM")),
		(_("%-d/%m"), _("Day D/MM")),
		(_("%d/%-m"), _("Day DD/M")),
		(_("%-d/%-m"), _("Day D/M")),
		(_("%b %d"), _("Day Mon DD")),
		(_("%b %-d"), _("Day Mon D")),
		(_("%b-%d"), _("Day Mon-DD")),
		(_("%b-%-d"), _("Day Mon-D")),
		(_("%m/%d"), _("Day MM/DD")),
		(_("%m/%-d"), _("Day MM/D")),
		(_("%-m/%d"), _("Day M/DD")),
		(_("%-m/%-d"), _("Day M/D"))
	])

	config.usage.date.displayday = ConfigText(default=_("%a %-d+%b_"))
	config.usage.date.display_template = ConfigText(default=_("%-d+%b_"))
	config.usage.date.compact = ConfigText(default=_("%-d+%b_"))
	config.usage.date.compressed = ConfigText(default=_("%-d+%b_"))

	timeDisplayValue = [_("%R")]

	def adjustDisplayDates():
		if timeDisplayValue[0] == "":
			if config.usage.date.display.value == "":  # If the date and time are both hidden output a space to blank the VFD display.
				config.usage.date.compact.value = " "
				config.usage.date.compressed.value = " "
			else:
				config.usage.date.compact.value = config.usage.date.displayday.value
				config.usage.date.compressed.value = config.usage.date.displayday.value
		else:
			if config.usage.time.wide_display.value:
				config.usage.date.compact.value = config.usage.date.display_template.value.replace("_", "").replace("=", "").replace("+", "")
				config.usage.date.compressed.value = config.usage.date.display_template.value.replace("_", "").replace("=", "").replace("+", "")
			else:
				config.usage.date.compact.value = config.usage.date.display_template.value.replace("_", " ").replace("=", "-").replace("+", " ")
				config.usage.date.compressed.value = config.usage.date.display_template.value.replace("_", " ").replace("=", "").replace("+", "")
		config.usage.date.compact.save()
		config.usage.date.compressed.save()

	def setDateDisplayStyles(configElement):
		dateDisplayStyles = {
			# display      displayday     template
			"": ("", ""),
			_("%d %b"): (_("%a %d %b"), _("%d+%b_")),
			_("%-d %b"): (_("%a %-d %b"), _("%-d+%b_")),
			_("%d-%b"): (_("%a %d-%b"), _("%d=%b_")),
			_("%-d-%b"): (_("%a %-d-%b"), _("%-d=%b_")),
			_("%d/%m"): (_("%a %d/%m"), _("%d/%m ")),
			_("%-d/%m"): (_("%a %-d/%m"), _("%-d/%m ")),
			_("%d/%-m"): (_("%a %d/%-m"), _("%d/%-m ")),
			_("%-d/%-m"): (_("%a %-d/%-m"), _("%-d/%-m ")),
			_("%b %d"): (_("%a %b %d"), _("%b+%d ")),
			_("%b %-d"): (_("%a %b %-d"), _("%b+%-d ")),
			_("%b-%d"): (_("%a %b-%d"), _("%b=%d ")),
			_("%b-%-d"): (_("%a %b-%-d"), _("%b=%-d ")),
			_("%m/%d"): (_("%a %m/%d"), _("%m/%d ")),
			_("%m/%-d"): (_("%a %m/%-d"), _("%m/%-d ")),
			_("%-m/%d"): (_("%a %-m/%d"), _("%-m/%d ")),
			_("%-m/%-d"): (_("%a %-m/%-d"), _("%-m/%-d "))
		}
		style = dateDisplayStyles.get(configElement.value, ((_("Invalid")) * 2))
		config.usage.date.displayday.value = style[0]
		config.usage.date.displayday.save()
		config.usage.date.display_template.value = style[1]
		config.usage.date.display_template.save()
		adjustDisplayDates()

	config.usage.date.display.addNotifier(setDateDisplayStyles)

	# TRANSLATORS: short time representation hour:minute (Same as "Default")
	if locale.nl_langinfo(locale.AM_STR) and locale.nl_langinfo(locale.PM_STR):
		config.usage.time.display = ConfigSelection(default=_("%R"), choices=[
			("", _("Hidden / Blank")),
			(_("%R"), _("HH:mm")),
			(_("%-H:%M"), _("H:mm")),
			(_("%I:%M%^p"), _("hh:mmAM/PM")),
			(_("%-I:%M%^p"), _("h:mmAM/PM")),
			(_("%I:%M%P"), _("hh:mmam/pm")),
			(_("%-I:%M%P"), _("h:mmam/pm")),
			(_("%I:%M"), _("hh:mm")),
			(_("%-I:%M"), _("h:mm"))
		])
	else:
		config.usage.time.display = ConfigSelection(default=_("%R"), choices=[
			("", _("Hidden / Blank")),
			(_("%R"), _("HH:mm")),
			(_("%-H:%M"), _("H:mm")),
			(_("%I:%M"), _("hh:mm")),
			(_("%-I:%M"), _("h:mm"))
		])

	def setTimeDisplayStyles(configElement):
		timeDisplayValue[0] = config.usage.time.display.value
		config.usage.time.wide_display.value = configElement.value.endswith(("P", "p"))
		adjustDisplayDates()

	config.usage.time.display.addNotifier(setTimeDisplayStyles)

	try:
		dateDisplayEnabled, timeDisplayEnabled = skin.parameters.get("AllowUserDatesAndTimesDisplay", (0, 0))
	except Exception as error:
		print("[UsageConfig] Error loading 'AllowUserDatesAndTimesDisplay' display skin parameter! (%s)" % error)
		dateDisplayEnabled, timeDisplayEnabled = (0, 0)
	if dateDisplayEnabled:
		config.usage.date.enabled_display.value = True
	else:
		config.usage.date.enabled_display.value = False
		config.usage.date.display.value = config.usage.date.display.default
	if timeDisplayEnabled:
		config.usage.time.enabled_display.value = True
	else:
		config.usage.time.enabled_display.value = False
		config.usage.time.display.value = config.usage.time.display.default

	config.usage.boolean_graphic = ConfigSelection(default="no", choices={"no": _("no"), "yes": _("yes"), "only_bool": _("yes, but not in multi selections")})
	config.usage.fast_skin_reload = ConfigYesNo(default=False)
	if not SystemInfo["DeveloperImage"]:
		config.usage.fast_skin_reload.value = False

	if SystemInfo["hasXcoreVFD"]:
		def set12to8characterVFD(configElement):
			open(SystemInfo["hasXcoreVFD"], "w").write(not configElement.value and "1" or "0")
		config.usage.toggle12to8characterVFD = ConfigYesNo(default=True)
		config.usage.toggle12to8characterVFD.addNotifier(set12to8characterVFD)

	config.epg = ConfigSubsection()
	config.epg.eit = ConfigYesNo(default=True)
	config.epg.mhw = ConfigYesNo(default=False)
	config.epg.freesat = ConfigYesNo(default=False)
	config.epg.viasat = ConfigYesNo(default=True)
	config.epg.netmed = ConfigYesNo(default=True)
	config.epg.virgin = ConfigYesNo(default=False)
	config.epg.opentv = ConfigYesNo(default=True)

	def EpgSettingsChanged(configElement):
		mask = 0xffffffff
		if not config.epg.eit.value:
			mask &= ~(eEPGCache.NOWNEXT | eEPGCache.SCHEDULE | eEPGCache.SCHEDULE_OTHER)
		if not config.epg.mhw.value:
			mask &= ~eEPGCache.MHW
		if not config.epg.freesat.value:
			mask &= ~(eEPGCache.FREESAT_NOWNEXT | eEPGCache.FREESAT_SCHEDULE | eEPGCache.FREESAT_SCHEDULE_OTHER)
		if not config.epg.viasat.value:
			mask &= ~eEPGCache.VIASAT
		if not config.epg.netmed.value:
			mask &= ~(eEPGCache.NETMED_SCHEDULE | eEPGCache.NETMED_SCHEDULE_OTHER)
		if not config.epg.virgin.value:
			mask &= ~(eEPGCache.VIRGIN_NOWNEXT | eEPGCache.VIRGIN_SCHEDULE)
		if not config.epg.opentv.value:
			mask &= ~eEPGCache.OPENTV
		eEPGCache.getInstance().setEpgSources(mask)
	config.epg.eit.addNotifier(EpgSettingsChanged)
	config.epg.mhw.addNotifier(EpgSettingsChanged)
	config.epg.freesat.addNotifier(EpgSettingsChanged)
	config.epg.viasat.addNotifier(EpgSettingsChanged)
	config.epg.netmed.addNotifier(EpgSettingsChanged)
	config.epg.virgin.addNotifier(EpgSettingsChanged)
	config.epg.opentv.addNotifier(EpgSettingsChanged)

	config.epg.histminutes = ConfigSelectionNumber(min=0, max=720, stepwidth=15, default=0, wraparound=True)
	config.epg.joinAbbreviatedEventNames = ConfigYesNo(default=True)
	config.epg.eventNamePrefixes = ConfigText(default="")
	config.epg.eventNamePrefixMode = ConfigSelection(choices=[(0, _("Off")), (1, _("Remove")), (2, _("Move to description"))])

	def EpgHistorySecondsChanged(configElement):
		eEPGCache.getInstance().setEpgHistorySeconds(config.epg.histminutes.value * 60)
	config.epg.histminutes.addNotifier(EpgHistorySecondsChanged)

	config.epg.cacheloadsched = ConfigYesNo(default=False)
	config.epg.cachesavesched = ConfigYesNo(default=False)

	def EpgCacheLoadSchedChanged(configElement):
		import Components.EpgLoadSave
		Components.EpgLoadSave.EpgCacheLoadCheck()

	def EpgCacheSaveSchedChanged(configElement):
		import Components.EpgLoadSave
		Components.EpgLoadSave.EpgCacheSaveCheck()
	config.epg.cacheloadsched.addNotifier(EpgCacheLoadSchedChanged, immediate_feedback=False)
	config.epg.cachesavesched.addNotifier(EpgCacheSaveSchedChanged, immediate_feedback=False)
	config.epg.cacheloadtimer = ConfigSelectionNumber(default=24, stepwidth=1, min=1, max=24, wraparound=True)
	config.epg.cachesavetimer = ConfigSelectionNumber(default=24, stepwidth=1, min=1, max=24, wraparound=True)

	def correctInvalidEPGDataChange(configElement):
		eServiceEvent.setUTF8CorrectMode(int(configElement.value))

	config.epg.correct_invalid_epgdata = ConfigSelection(default="1", choices=[
		("0", _("Disabled")),
		("1", _("Enabled")),
		("2", _("Debug"))
	])
	config.epg.correct_invalid_epgdata.addNotifier(correctInvalidEPGDataChange)

	hddchoices = [("/etc/enigma2/", "Internal Flash")]
	for p in harddiskmanager.getMountedPartitions():
		if os.path.exists(p.mountpoint):
			d = os.path.normpath(p.mountpoint)
			if p.mountpoint != "/":
				hddchoices.append((p.mountpoint, d))
	config.misc.epgcachepath = ConfigSelection(default='/etc/enigma2/', choices=hddchoices)
	config.misc.epgcachefilename = ConfigText(default='epg', fixed_size=False)
	config.misc.epgcache_filename = ConfigText(default=(config.misc.epgcachepath.value + config.misc.epgcachefilename.value.replace('.dat', '') + '.dat'))

	def EpgCacheChanged(configElement):
		config.misc.epgcache_filename.setValue(os.path.join(config.misc.epgcachepath.value, config.misc.epgcachefilename.value.replace('.dat', '') + '.dat'))
		config.misc.epgcache_filename.save()
		eEPGCache.getInstance().setCacheFile(config.misc.epgcache_filename.value)
		epgcache = eEPGCache.getInstance()
		epgcache.save()
		if not config.misc.epgcache_filename.value.startswith("/etc/enigma2/"):
			if os.path.exists('/etc/enigma2/' + config.misc.epgcachefilename.value.replace('.dat', '') + '.dat'):
				os.remove('/etc/enigma2/' + config.misc.epgcachefilename.value.replace('.dat', '') + '.dat')
	config.misc.epgcachepath.addNotifier(EpgCacheChanged, immediate_feedback=False)
	config.misc.epgcachefilename.addNotifier(EpgCacheChanged, immediate_feedback=False)

	config.misc.epgratingcountry = ConfigSelection(default="", choices=[("", _("Auto Detect")), ("ETSI", _("Generic")), ("AUS", _("Australia"))])
	config.misc.epggenrecountry = ConfigSelection(default="", choices=[("", _("Auto Detect")), ("ETSI", _("Generic")), ("AUS", _("Australia"))])

	config.misc.showradiopic = ConfigYesNo(default=True)

	def setHDDStandby(configElement):
		for hdd in harddiskmanager.HDDList():
			hdd[1].setIdleTime(int(configElement.value))
	config.usage.hdd_standby.addNotifier(setHDDStandby, immediate_feedback=False)

	if SystemInfo["12V_Output"]:
		def set12VOutput(configElement):
			Misc_Options.getInstance().set_12V_output(configElement.value == "on" and 1 or 0)
		config.usage.output_12V.addNotifier(set12VOutput, immediate_feedback=False)

	config.usage.keymap = ConfigText(default=eEnv.resolve("${datadir}/enigma2/keymap.xml"))
	keytranslation = eEnv.resolve("${sysconfdir}/enigma2/keytranslation.xml")
	if not os.path.exists(keytranslation):
		keytranslation = eEnv.resolve("${datadir}/enigma2/keytranslation.xml")
	config.usage.keytrans = ConfigText(default=keytranslation)

	config.network = ConfigSubsection()

	config.network.AFP_autostart = ConfigYesNo(default=True)
	config.network.NFS_autostart = ConfigYesNo(default=True)
	config.network.OpenVPN_autostart = ConfigYesNo(default=True)
	config.network.Samba_autostart = ConfigYesNo(default=True)
	config.network.Inadyn_autostart = ConfigYesNo(default=True)
	config.network.uShare_autostart = ConfigYesNo(default=True)

	config.softwareupdate = ConfigSubsection()
	config.softwareupdate.autosettingsbackup = ConfigYesNo(default=True)
	config.softwareupdate.autoimagebackup = ConfigYesNo(default=False)
	config.softwareupdate.check = ConfigYesNo(default=True)
	config.softwareupdate.checktimer = ConfigSelectionNumber(min=1, max=48, stepwidth=1, default=24, wraparound=True)
	config.softwareupdate.updatelastcheck = ConfigInteger(default=0)
	config.softwareupdate.updatefound = NoSave(ConfigBoolean(default=False))
	config.softwareupdate.updatebeta = ConfigYesNo(default=False)
	config.softwareupdate.updateisunstable = ConfigInteger(default=0)
	config.softwareupdate.showinextensions = ConfigSelection(default="no", choices=[("no", _("no")), ("yes", _("yes")), ("available", _("only when available"))])

	config.timeshift = ConfigSubsection()
	choicelist = [("0", _("Disabled"))]
	for i in (2, 3, 4, 5, 10, 20, 30):
		choicelist.append(("%d" % i, ngettext("%d second", "%d seconds", i) % i))
	for i in (60, 120, 300):
		m = i / 60
		choicelist.append(("%d" % i, ngettext("%d minute", "%d minutes", m) % m))
	config.timeshift.startdelay = ConfigSelection(default="0", choices=choicelist)
	config.timeshift.showinfobar = ConfigYesNo(default=True)
	config.timeshift.stopwhilerecording = ConfigYesNo(default=False)
	config.timeshift.favoriteSaveAction = ConfigSelection([("askuser", _("Ask user")), ("savetimeshift", _("Save and stop")), ("savetimeshiftandrecord", _("Save and record")), ("noSave", _("Don't save"))], "askuser")
	config.timeshift.permanentrecording = ConfigYesNo(default=False)
	config.timeshift.isRecording = NoSave(ConfigYesNo(default=False))
	config.timeshift.stream_warning = ConfigYesNo(default=True)

	config.seek = ConfigSubsection()
	config.seek.baractivation = ConfigSelection([("leftright", _("Long Left/Right")), ("ffrw", _("Long << / >>"))], "leftright")
	config.seek.sensibility = ConfigSelectionNumber(min=1, max=10, stepwidth=1, default=10, wraparound=True)
	config.seek.selfdefined_13 = ConfigSelectionNumber(min=1, max=120, stepwidth=1, default=15, wraparound=True)
	config.seek.selfdefined_46 = ConfigSelectionNumber(min=1, max=240, stepwidth=1, default=60, wraparound=True)
	config.seek.selfdefined_79 = ConfigSelectionNumber(min=1, max=480, stepwidth=1, default=300, wraparound=True)

	config.seek.speeds_forward = ConfigSet(default=[2, 4, 8, 16, 32, 64, 128], choices=[2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128])
	config.seek.speeds_backward = ConfigSet(default=[2, 4, 8, 16, 32, 64, 128], choices=[1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128])
	config.seek.speeds_slowmotion = ConfigSet(default=[2, 4, 8], choices=[2, 4, 6, 8, 12, 16, 25])

	config.seek.enter_forward = ConfigSelection(default="2", choices=["2", "4", "6", "8", "12", "16", "24", "32", "48", "64", "96", "128"])
	config.seek.enter_backward = ConfigSelection(default="1", choices=["1", "2", "4", "6", "8", "12", "16", "24", "32", "48", "64", "96", "128"])

	config.seek.on_pause = ConfigSelection(default="play", choices=[
		("play", _("Play")),
		("step", _("Single step (GOP)")),
		("last", _("Last speed"))])

	config.crash = ConfigSubsection()
	config.crash.enabledebug = ConfigYesNo(default=False)
	config.crash.e2_debug_level = ConfigSelection(default=4, choices=[(3, _("No Logs")), (4, _("Debug Logs")), (5, _("Debug+ Logs"))])
	config.crash.debugloglimit = ConfigSelectionNumber(min=1, max=10, stepwidth=1, default=4, wraparound=True)

# Just echo CHANGE var=val for the logger process to find.
# Send a newline at the start in case some background process hasn't
#
	def report_debugloglimit_change(configElement):
		raw_stderr_print("\nCHANGE config.crash.debugloglimit=%d\n" % config.crash.debugloglimit.value)
	config.crash.debugloglimit.addNotifier(report_debugloglimit_change, immediate_feedback=False)
	config.crash.daysloglimit = ConfigSelectionNumber(min=1, max=30, stepwidth=1, default=8, wraparound=True)
	config.crash.sizeloglimit = ConfigSelectionNumber(min=1, max=20, stepwidth=1, default=10, wraparound=True)
	# config.crash.logtimeformat sets ENIGMA_DEBUG_TIME environmental variable on enigma2 start from enigma2.sh
	config.crash.logtimeformat = ConfigSelection(default="1", choices=[
		("0", _("none")),
		("1", _("boot time")),
		("2", _("local time")),
		("3", _("boot time and local time"))])
	config.crash.logtimeformat.save_forced = True

	debugpath = [('/home/root/logs/', '/home/root/')]
	for p in harddiskmanager.getMountedPartitions():
		if os.path.exists(p.mountpoint):
			d = os.path.normpath(p.mountpoint)
			if p.mountpoint != '/':
				debugpath.append((p.mountpoint + 'logs/', d))
	config.crash.debug_path = ConfigSelection(default="/home/root/logs/", choices=debugpath)

# Just echo CHANGE var=val for the logger process to find.
# Send a newline at the start in case some background process hasn't
#
	def report_debugpath_change(configElement):
		raw_stderr_print("\nCHANGE config.crash.debug_path=%s\n" % config.crash.debug_path.value)
	config.crash.debug_path.addNotifier(report_debugpath_change, immediate_feedback=False)

	def updatedebug_path(configElement):
		if not os.path.exists(config.crash.debug_path.value):
			os.mkdir(config.crash.debug_path.value, 0o755)
	config.crash.debug_path.addNotifier(updatedebug_path, immediate_feedback=False)
	config.crash.coredump = ConfigYesNo(default=False)

	config.usage.timerlist_showpicons = ConfigYesNo(default=True)
	config.usage.timerlist_finished_timer_position = ConfigSelection(default="end", choices=[("beginning", _("at beginning")), ("end", _("at end")), ("hide", _("hide"))])

	def updateEnterForward(configElement):
		if not configElement.value:
			configElement.value = [2]
		updateChoices(config.seek.enter_forward, configElement.value)

	config.seek.speeds_forward.addNotifier(updateEnterForward, immediate_feedback=False)

	def updateEnterBackward(configElement):
		if not configElement.value:
			configElement.value = [2]
		updateChoices(config.seek.enter_backward, configElement.value)

	config.seek.speeds_backward.addNotifier(updateEnterBackward, immediate_feedback=False)

	config.misc.zapkey_delay = ConfigSelectionNumber(default=5, stepwidth=1, min=0, max=20, wraparound=True)
	config.misc.numzap_picon = ConfigYesNo(default=False)
	if SystemInfo["ZapMode"]:
		def setZapmode(el):
			file = open(SystemInfo["ZapMode"], "w")
			file.write(el.value)
			file.close()
		config.misc.zapmode = ConfigSelection(default="mute", choices=[
			("mute", _("Black screen")), ("hold", _("Hold screen")), ("mutetilllock", _("Black screen till locked")), ("holdtilllock", _("Hold till locked"))])
		config.misc.zapmode.addNotifier(setZapmode, immediate_feedback=False)
	config.usage.historymode = ConfigSelection(default="1", choices=[("0", _("Just zap")), ("1", _("Show menu"))])

	config.subtitles = ConfigSubsection()
	config.subtitles.ttx_subtitle_colors = ConfigSelection(default="1", choices=[
		("0", _("original")),
		("1", _("white")),
		("2", _("yellow"))])
	config.subtitles.ttx_subtitle_original_position = ConfigYesNo(default=False)
	config.subtitles.subtitle_position = ConfigSelection(choices=["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "150", "200", "250", "300", "350", "400", "450"], default="50")
	config.subtitles.subtitle_alignment = ConfigSelection(choices=[("left", _("left")), ("center", _("center")), ("right", _("right"))], default="center")
	config.subtitles.subtitle_rewrap = ConfigYesNo(default=False)
	config.subtitles.colourise_dialogs = ConfigYesNo(default=False)
	config.subtitles.subtitle_borderwidth = ConfigSelection(choices=["1", "2", "3", "4", "5"], default="3")
	config.subtitles.subtitle_fontsize = ConfigSelection(choices=["%d" % x for x in range(16, 101) if not x % 2], default="40")
	config.subtitles.showbackground = ConfigYesNo(default=False)

	subtitle_delay_choicelist = []
	for i in range(-900000, 1845000, 45000):
		if i == 0:
			subtitle_delay_choicelist.append(("0", _("No delay")))
		else:
			subtitle_delay_choicelist.append((str(i), _("%2.1f sec") % (i / 90000.)))
	config.subtitles.subtitle_noPTSrecordingdelay = ConfigSelection(default="315000", choices=subtitle_delay_choicelist)

	config.subtitles.dvb_subtitles_yellow = ConfigYesNo(default=False)
	config.subtitles.dvb_subtitles_original_position = ConfigSelection(default="0", choices=[("0", _("Original")), ("1", _("Fixed")), ("2", _("Relative"))])
	config.subtitles.dvb_subtitles_centered = ConfigYesNo(default=False)
	config.subtitles.subtitle_bad_timing_delay = ConfigSelection(default="0", choices=subtitle_delay_choicelist)
	config.subtitles.dvb_subtitles_backtrans = ConfigSelection(default="0", choices=[
		("0", _("No transparency")),
		("25", "10%"),
		("50", "20%"),
		("75", "30%"),
		("100", "40%"),
		("125", "50%"),
		("150", "60%"),
		("175", "70%"),
		("200", "80%"),
		("225", "90%"),
		("255", _("Full transparency"))])
	config.subtitles.pango_subtitle_colors = ConfigSelection(default="1", choices=[
		("0", _("alternative")),
		("1", _("white")),
		("2", _("yellow"))])
	config.subtitles.pango_subtitle_fontswitch = ConfigYesNo(default=True)
	config.subtitles.pango_subtitles_delay = ConfigSelection(default="0", choices=subtitle_delay_choicelist)
	config.subtitles.pango_subtitles_fps = ConfigSelection(default="1", choices=[
		("1", _("Original")),
		("23976", _("23.976")),
		("24000", _("24")),
		("25000", _("25")),
		("29970", _("29.97")),
		("30000", _("30"))])
	config.subtitles.pango_subtitle_removehi = ConfigYesNo(default=False)
	config.subtitles.pango_autoturnon = ConfigYesNo(default=True)

	config.autolanguage = ConfigSubsection()
	default_autoselect = "eng Englisch"  # for audio_autoselect1
	audio_language_choices = [
		("", _("None")),
		("und", _("Undetermined")),
		(originalAudioTracks, _("Original language")),
		("ara", _("Arabic")),
		("eus baq", _("Basque")),
		("bul", _("Bulgarian")),
		("hrv", _("Croatian")),
		("ces cze", _("Czech")),
		("dan", _("Danish")),
		("dut ndl nld Dutch", _("Dutch")),
		(default_autoselect, _("English")),
		("est", _("Estonian")),
		("fin", _("Finnish")),
		("fra fre", _("French")),
		("deu ger", _("German")),
		("ell gre", _("Greek")),
		("heb", _("Hebrew")),
		("hun", _("Hungarian")),
		("ita", _("Italian")),
		("lav", _("Latvian")),
		("lit", _("Lithuanian")),
		("ltz", _("Luxembourgish")),
		("nor", _("Norwegian")),
		("pol", _("Polish")),
		("por dub Dub DUB ud1", _("Portuguese")),
		("fas per fa pes", _("Persian")),
		("ron rum", _("Romanian")),
		("rus", _("Russian")),
		("srp", _("Serbian")),
		("slk slo", _("Slovak")),
		("slv", _("Slovenian")),
		("spa", _("Spanish")),
		("swe", _("Swedish")),
		("tha", _("Thai")),
		("tur Audio_TUR", _("Turkish")),
		("ukr Ukr", _("Ukrainian")),
		(visuallyImpairedCommentary, _("Narration"))]

	def setEpgLanguage(configElement):
		eServiceEvent.setEPGLanguage(configElement.value)
	config.autolanguage.audio_epglanguage = ConfigSelection(audio_language_choices[:1] + audio_language_choices[2:], default="")
	config.autolanguage.audio_epglanguage.addNotifier(setEpgLanguage)

	def setEpgLanguageAlternative(configElement):
		eServiceEvent.setEPGLanguageAlternative(configElement.value)
	config.autolanguage.audio_epglanguage_alternative = ConfigSelection(audio_language_choices[:1] + audio_language_choices[2:], default="")
	config.autolanguage.audio_epglanguage_alternative.addNotifier(setEpgLanguageAlternative)

	config.autolanguage.audio_autoselect1 = ConfigSelection(choices=audio_language_choices, default=default_autoselect)
	config.autolanguage.audio_autoselect2 = ConfigSelection(choices=audio_language_choices, default="")
	config.autolanguage.audio_autoselect3 = ConfigSelection(choices=audio_language_choices, default="")
	config.autolanguage.audio_autoselect4 = ConfigSelection(choices=audio_language_choices, default="")
	config.autolanguage.audio_defaultac3 = ConfigYesNo(default=True)
	config.autolanguage.audio_defaultddp = ConfigYesNo(default=False)
	config.autolanguage.audio_usecache = ConfigYesNo(default=True)

	subtitle_language_choices = audio_language_choices[:1] + audio_language_choices[2:]
	config.autolanguage.subtitle_autoselect1 = ConfigSelection(choices=subtitle_language_choices, default="")
	config.autolanguage.subtitle_autoselect2 = ConfigSelection(choices=subtitle_language_choices, default="")
	config.autolanguage.subtitle_autoselect3 = ConfigSelection(choices=subtitle_language_choices, default="")
	config.autolanguage.subtitle_autoselect4 = ConfigSelection(choices=subtitle_language_choices, default="")
	config.autolanguage.subtitle_hearingimpaired = ConfigYesNo(default=False)
	config.autolanguage.subtitle_defaultimpaired = ConfigYesNo(default=False)
	config.autolanguage.subtitle_defaultdvb = ConfigYesNo(default=False)
	config.autolanguage.subtitle_usecache = ConfigYesNo(default=True)
	config.autolanguage.equal_languages = ConfigSelection(default="15", choices=[
		("0", _("None")), ("1", "1"), ("2", "2"), ("3", "1,2"),
		("4", "3"), ("5", "1,3"), ("6", "2,3"), ("7", "1,2,3"),
		("8", "4"), ("9", "1,4"), ("10", "2,4"), ("11", "1,2,4"),
		("12", "3,4"), ("13", "1,3,4"), ("14", "2,3,4"), ("15", _("All"))])

	config.logmanager = ConfigSubsection()
	config.logmanager.showinextensions = ConfigYesNo(default=False)
	config.logmanager.path = ConfigText(default="/")
	config.logmanager.sentfiles = ConfigLocations(default='')

	config.vixsettings = ConfigSubsection()
	config.vixsettings.Subservice = ConfigYesNo(default=False)
	config.vixsettings.ColouredButtons = ConfigYesNo(default=True)
	config.vixsettings.InfoBarEpg_mode = ConfigSelection(default="3", choices=[
					("0", _("as plugin in extended bar")),
					("1", _("with long OK press")),
					("2", _("with exit button")),
					("3", _("with left/right buttons"))])

	if not os.path.exists('/usr/softcams/'):
		os.mkdir('/usr/softcams/', 0o755)
	softcams = os.listdir('/usr/softcams/')
	config.oscaminfo = ConfigSubsection()
	config.oscaminfo.showInExtensions = ConfigYesNo(default=False)
	config.oscaminfo.userdatafromconf = ConfigYesNo(default=True)
	config.oscaminfo.autoupdate = ConfigYesNo(default=False)
	config.oscaminfo.username = ConfigText(default="username", fixed_size=False, visible_width=12)
	config.oscaminfo.password = ConfigPassword(default="password", fixed_size=False)
	config.oscaminfo.ip = ConfigIP(default=[127, 0, 0, 1], auto_jump=True)
	config.oscaminfo.port = ConfigInteger(default=16002, limits=(0, 65536))
	config.oscaminfo.intervall = ConfigSelectionNumber(min=1, max=600, stepwidth=1, default=10, wraparound=True)
	config.misc.enableCamscript = ConfigYesNo(default=False)
	config.misc.softcams = ConfigSelection(default="None", choices=[(x, _(x)) for x in CamControl("softcam").getList()])
	config.misc.softcamrestarts = ConfigSelection(default="", choices=[
					("", _("Don't restart")),
					("s", _("Restart softcam"))])
	SystemInfo["OScamInstalled"] = False

	config.cccaminfo = ConfigSubsection()
	config.cccaminfo.showInExtensions = ConfigYesNo(default=False)
	config.cccaminfo.serverNameLength = ConfigSelectionNumber(min=10, max=100, stepwidth=1, default=22, wraparound=True)
	config.cccaminfo.name = ConfigText(default="Profile", fixed_size=False)
	config.cccaminfo.ip = ConfigText(default="192.168.2.12", fixed_size=False)
	config.cccaminfo.username = ConfigText(default="", fixed_size=False)
	config.cccaminfo.password = ConfigText(default="", fixed_size=False)
	config.cccaminfo.port = ConfigInteger(default=16001, limits=(1, 65535))
	config.cccaminfo.profile = ConfigText(default="", fixed_size=False)
	config.cccaminfo.ecmInfoEnabled = ConfigYesNo(default=True)
	config.cccaminfo.ecmInfoTime = ConfigSelectionNumber(min=1, max=10, stepwidth=1, default=5, wraparound=True)
	config.cccaminfo.ecmInfoForceHide = ConfigYesNo(default=True)
	config.cccaminfo.ecmInfoPositionX = ConfigInteger(default=50)
	config.cccaminfo.ecmInfoPositionY = ConfigInteger(default=50)
	config.cccaminfo.blacklist = ConfigText(default="/media/cf/CCcamInfo.blacklisted", fixed_size=False)
	config.cccaminfo.profiles = ConfigText(default="/media/cf/CCcamInfo.profiles", fixed_size=False)
	SystemInfo["CCcamInstalled"] = False
	for softcam in softcams:
		if softcam.lower().startswith("cccam"):
			config.cccaminfo.showInExtensions = ConfigYesNo(default=True)
			SystemInfo["CCcamInstalled"] = True
		elif softcam.lower().startswith('oscam') or softcam.lower().startswith('ncam'):
			config.oscaminfo.showInExtensions = ConfigYesNo(default=True)
			SystemInfo["OScamInstalled"] = True

	config.streaming = ConfigSubsection()
	config.streaming.stream_ecm = ConfigYesNo(default=False)
	config.streaming.descramble = ConfigYesNo(default=True)
	config.streaming.descramble_client = ConfigYesNo(default=False)
	config.streaming.stream_eit = ConfigYesNo(default=True)
	config.streaming.stream_ait = ConfigYesNo(default=True)
	config.streaming.authentication = ConfigYesNo(default=False)

	config.pluginbrowser = ConfigSubsection()
	config.pluginbrowser.po = ConfigYesNo(default=False)
	config.pluginbrowser.src = ConfigYesNo(default=False)

	config.mediaplayer = ConfigSubsection()
	config.mediaplayer.useAlternateUserAgent = ConfigYesNo(default=False)
	config.mediaplayer.alternateUserAgent = ConfigText(default="")

	config.hdmicec = ConfigSubsection()
	config.hdmicec.enabled = ConfigYesNo(default=False)
	config.hdmicec.control_tv_standby = ConfigYesNo(default=True)
	config.hdmicec.control_tv_wakeup = ConfigYesNo(default=True)
	config.hdmicec.report_active_source = ConfigYesNo(default=True)
	config.hdmicec.report_active_menu = ConfigYesNo(default=True)
	config.hdmicec.handle_tv_standby = ConfigYesNo(default=True)
	config.hdmicec.handle_tv_wakeup = ConfigYesNo(default=True)
	config.hdmicec.tv_wakeup_detection = ConfigSelection(
		choices={
		"wakeup": _("Wakeup"),
		"requestphysicaladdress": _("Request for physical address report"),
		"tvreportphysicaladdress": _("TV physical address report"),
		"routingrequest": _("Routing request"),
		"sourcerequest": _("Source request"),
		"streamrequest": _("Stream request"),
		"requestvendor": _("Request for vendor report"),
		"osdnamerequest": _("OSD name request"),
		"activity": _("Any activity"),
		},
		default="streamrequest")
	config.hdmicec.tv_wakeup_command = ConfigSelection(
		choices={
		"imageview": _("Image View On"),
		"textview": _("Text View On"),
		},
		default="imageview")
	config.hdmicec.fixed_physical_address = ConfigText(default="0.0.0.0")
	config.hdmicec.volume_forwarding = ConfigYesNo(default=False)
	config.hdmicec.force_volume_forwarding = ConfigYesNo(default=False)
	config.hdmicec.control_receiver_wakeup = ConfigYesNo(default=False)
	config.hdmicec.control_receiver_standby = ConfigYesNo(default=False)
	config.hdmicec.handle_deepstandby_events = ConfigYesNo(default=False)
	choicelist = []
	for i in (10, 50, 100, 150, 250, 500, 750, 1000):
		choicelist.append(("%d" % i, _("%d ms") % i))
	config.hdmicec.minimum_send_interval = ConfigSelection(default="0", choices=[("0", _("Disabled"))] + choicelist)
	choicelist = []
	for i in [3] + list(range(5, 65, 5)):
		choicelist.append(("%d" % i, _("%d sec") % i))
	config.hdmicec.repeat_wakeup_timer = ConfigSelection(default="3", choices=[("0", _("Disabled"))] + choicelist)
	config.hdmicec.debug = ConfigSelection(default="0", choices=[("0", _("Disabled")), ("1", _("Messages")), ("2", _("Key Events")), ("3", _("All"))])
	config.hdmicec.bookmarks = ConfigLocations(default="/hdd/")
	config.hdmicec.log_path = ConfigDirectory("/hdd/")
	config.hdmicec.next_boxes_detect = ConfigYesNo(default=False)  # Before switching the TV to standby, receiver tests if any devices plugged to TV are in standby. If they are not, the 'sourceinactive' command will be sent to the TV instead of the 'standby' command.
	config.hdmicec.sourceactive_zaptimers = ConfigYesNo(default=False)				# Command the TV to switch to the correct HDMI input when zap timers activate.

	upgradeConfig()

	# now that the config upgrade has been processed, it's safe to reintroduce any settings
	# required for backwards compatibility with plugins. These will mirror the new settings
	config.epgselection.enhanced_eventfs = config.epgselection.single.eventfs
	config.epgselection.enhanced_itemsperpage = config.epgselection.single.itemsperpage


def updateChoices(sel, choices):
	if choices:
		defval = None
		val = int(sel.value)
		if val not in choices:
			tmp = choices[:]
			tmp.reverse()
			for x in tmp:
				if x < val:
					defval = str(x)
					break
		sel.setChoices(list(map(str, choices)), defval)


def preferredPath(path):
	if config.usage.setup_level.index < 2 or path == "<default>":
		return None  # config.usage.default_path.value, but delay lookup until usage
	elif path == "<current>":
		return config.movielist.last_videodir.value
	elif path == "<timer>":
		return config.movielist.last_timer_videodir.value
	else:
		return path


def preferredTimerPath():
	return preferredPath(config.usage.timer_path.value)


def preferredInstantRecordPath():
	return preferredPath(config.usage.instantrec_path.value)


def defaultMoviePath():
	return defaultRecordingLocation(config.usage.default_path.value)


def showrotorpositionChoicesUpdate(update=False):
	choiceslist = [("no", _("no")), ("yes", _("yes")), ("withtext", _("with text")), ("tunername", _("with tuner name"))]
	count = 0
	for x in nimmanager.nim_slots:
		if nimmanager.getRotorSatListForNim(x.slot, only_first=True):
			choiceslist.append((str(x.slot), x.getSlotName() + _(" (auto detection)")))
			count += 1
	if count > 1:
		choiceslist.append(("all", _("all tuners") + _(" (auto detection)")))
		choiceslist.remove(("tunername", _("with tuner name")))
	if not update:
		config.misc.showrotorposition = ConfigSelection(default="no", choices=choiceslist)
	else:
		config.misc.showrotorposition.setChoices(choiceslist, "no")
	SystemInfo["isRotorTuner"] = count > 0


def upgradeConfig():
	if config.version.value < 53023:
		def getOldValue(name):
			value = config.content.stored_values
			found = True
			for n in name.split("."):
				value = value.get(n, None)
				if value is None:
					found = False
					break
			# this value is a string, not the actual type required by the config item
			return value if found else None

		def upgrade(configItem, name, valuemap=None, mapper=None):
			value = getOldValue(name)
			if value is not None:
				# this value is a string, not the actual type required by the config item
				newvalue = None
				if valuemap is not None:
					newvalue = valuemap.get(value, None)
				if newvalue is None and mapper is not None:
					newvalue = mapper(value)
				if newvalue is not None:
					print("[UsageConfig] upgrading %s, mapping value %s to %s" % (name, value, newvalue))
				else:
					print("[UsageConfig] upgrading %s, value %s" % (name, value))
					newvalue = value
				if newvalue is not None:
					# load the string value to convert it to the config item's type
					configItem.saved_value = newvalue
					configItem.load()

		print("[UsageConfig] Upgrading EPG settings")

		okMap = {"Zap + Exit": "zapExit", "Zap": "zap"}
		infoMap = {"Channel Info": "openEventView", "Single EPG": "openSingleEPG"}

		upgrade(config.epgselection.infobar.type_mode, "epgselection.infobar_type_mode")
		upgrade(config.epgselection.infobar.preview_mode, "epgselection.infobar_preview_mode")
		upgrade(config.epgselection.infobar.btn_ok, "epgselection.infobar_ok", okMap)
		upgrade(config.epgselection.infobar.btn_oklong, "epgselection.infobar_oklong", okMap)
		upgrade(config.epgselection.infobar.itemsperpage, "epgselection.infobar_itemsperpage")
		upgrade(config.epgselection.infobar.roundto, "epgselection.infobar_roundto")
		upgrade(config.epgselection.infobar.prevtimeperiod, "epgselection.infobar_prevtimeperiod")
		upgrade(config.epgselection.infobar.primetime, "epgselection.infobar_primetimehour", mapper=lambda v: v + ":00")
		upgrade(config.epgselection.infobar.servicetitle_mode, "epgselection.infobar_servicetitle_mode", {"servicenumber+picon": "picon+servicenumber", "servicenumber+picon+servicename": "picon+servicenumber+servicename"})
		upgrade(config.epgselection.infobar.servfs, "epgselection.infobar_servfs")
		upgrade(config.epgselection.infobar.eventfs, "epgselection.infobar_eventfs")
		upgrade(config.epgselection.infobar.timelinefs, "epgselection.infobar_timelinefs")
		upgrade(config.epgselection.infobar.timeline24h, "epgselection.infobar_timeline24h")
		upgrade(config.epgselection.infobar.servicewidth, "epgselection.infobar_servicewidth")
		upgrade(config.epgselection.infobar.piconwidth, "epgselection.infobar_piconwidth")
		upgrade(config.epgselection.infobar.infowidth, "epgselection.infobar_infowidth")

		upgrade(config.epgselection.single.preview_mode, "epgselection.enhanced_preview_mode")
		upgrade(config.epgselection.single.btn_ok, "epgselection.enhanced_ok", okMap)
		upgrade(config.epgselection.single.btn_oklong, "epgselection.enhanced_oklong", okMap)
		upgrade(config.epgselection.single.eventfs, "epgselection.enhanced_eventfs")
		upgrade(config.epgselection.single.itemsperpage, "epgselection.enhanced_itemsperpage")

		upgrade(config.epgselection.multi.showbouquet, "epgselection.multi_showbouquet")
		upgrade(config.epgselection.multi.preview_mode, "epgselection.multi_preview_mode")
		upgrade(config.epgselection.multi.btn_ok, "epgselection.multi_ok", okMap)
		upgrade(config.epgselection.multi.btn_oklong, "epgselection.multi_oklong", okMap)
		upgrade(config.epgselection.multi.eventfs, "epgselection.multi_eventfs")
		upgrade(config.epgselection.multi.itemsperpage, "epgselection.multi_itemsperpage")

		upgrade(config.epgselection.grid.showbouquet, "epgselection.graph_showbouquet")
		upgrade(config.epgselection.grid.browse_mode, "epgselection.graph_channel1", {"True": "firstservice", "False": "currentservice"})
		upgrade(config.epgselection.grid.preview_mode, "epgselection.graph_preview_mode")
		upgrade(config.epgselection.grid.type_mode, "epgselection.graph_type_mode")
		upgrade(config.epgselection.grid.highlight_current_events, "epgselection.graph_highlight_current_events")
		upgrade(config.epgselection.grid.btn_ok, "epgselection.graph_ok", okMap)
		upgrade(config.epgselection.grid.btn_oklong, "epgselection.graph_oklong", okMap)
		upgrade(config.epgselection.grid.btn_info, "epgselection.graph_info", infoMap)
		upgrade(config.epgselection.grid.btn_infolong, "epgselection.graph_infolong", infoMap)
		upgrade(config.epgselection.grid.roundto, "epgselection.graph_roundto")
		upgrade(config.epgselection.grid.prevtimeperiod, "epgselection.graph_prevtimeperiod")
		upgrade(config.epgselection.grid.primetime, "epgselection.graph_primetimehour", mapper=lambda v: v + ":00")
		upgrade(config.epgselection.grid.servicetitle_mode, "epgselection.graph_servicetitle_mode", {"servicenumber+picon": "picon+servicenumber", "servicenumber+picon+servicename": "picon+servicenumber+servicename"})
		upgrade(config.epgselection.grid.servicename_alignment, "epgselection.graph_servicename_alignment")
		upgrade(config.epgselection.grid.servicenumber_alignment, "epgselection.graph_servicenumber_alignment")
		upgrade(config.epgselection.grid.event_alignment, "epgselection.graph_event_alignment")
		upgrade(config.epgselection.grid.timelinedate_alignment, "epgselection.graph_timelinedate_alignment")
		upgrade(config.epgselection.grid.servfs, "epgselection.graph_servfs")
		upgrade(config.epgselection.grid.eventfs, "epgselection.graph_eventfs")
		upgrade(config.epgselection.grid.timelinefs, "epgselection.graph_timelinefs")
		upgrade(config.epgselection.grid.timeline24h, "epgselection.graph_timeline24h")
		upgrade(config.epgselection.grid.itemsperpage, "epgselection.graph_itemsperpage")
		upgrade(config.epgselection.grid.pig, "epgselection.graph_pig")
		upgrade(config.epgselection.grid.servicewidth, "epgselection.graph_servicewidth")
		upgrade(config.epgselection.grid.piconwidth, "epgselection.graph_piconwidth")
		upgrade(config.epgselection.grid.infowidth, "epgselection.graph_infowidth")
		upgrade(config.epgselection.grid.rec_icon_height, "epgselection.graph_rec_icon_height")
		for (key, item) in config.misc.ButtonSetup.content.items.items():
			if item.value == "Infobar/openGraphEPG":
				item.value = "Infobar/openGridEPG"
				item.save()
		config.version.value = "53023"
		config.version.save()


def preferredTunerChoicesUpdate(update=False):
	dvbs_nims = [("-2", _("disabled"))]
	dvbt_nims = [("-2", _("disabled"))]
	dvbc_nims = [("-2", _("disabled"))]
	atsc_nims = [("-2", _("disabled"))]

	nims = [("-1", _("auto"))]
	for slot in nimmanager.nim_slots:
		if hasattr(slot.config, "configMode") and slot.config.configMode.value == "nothing":
			continue
		if slot.isCompatible("DVB-S"):
			dvbs_nims.append((str(slot.slot), slot.getSlotName()))
		elif slot.isCompatible("DVB-T"):
			dvbt_nims.append((str(slot.slot), slot.getSlotName()))
		elif slot.isCompatible("DVB-C"):
			dvbc_nims.append((str(slot.slot), slot.getSlotName()))
		elif slot.isCompatible("ATSC"):
			atsc_nims.append((str(slot.slot), slot.getSlotName()))
		nims.append((str(slot.slot), slot.getSlotName()))

	if not update:
		config.usage.frontend_priority = ConfigSelection(default="-1", choices=list(nims))
	else:
		config.usage.frontend_priority.setChoices(list(nims), "-1")
	nims.insert(0, ("-2", _("disabled")))
	if not update:
		config.usage.recording_frontend_priority = ConfigSelection(default="-2", choices=nims)
	else:
		config.usage.recording_frontend_priority.setChoices(nims, "-2")
	if not update:
		config.usage.frontend_priority_dvbs = ConfigSelection(default="-2", choices=list(dvbs_nims))
	else:
		config.usage.frontend_priority_dvbs.setChoices(list(dvbs_nims), "-2")
	dvbs_nims.insert(1, ("-1", _("auto")))
	if not update:
		config.usage.recording_frontend_priority_dvbs = ConfigSelection(default="-2", choices=dvbs_nims)
	else:
		config.usage.recording_frontend_priority_dvbs.setChoices(dvbs_nims, "-2")
	if not update:
		config.usage.frontend_priority_dvbt = ConfigSelection(default="-2", choices=list(dvbt_nims))
	else:
		config.usage.frontend_priority_dvbt.setChoices(list(dvbt_nims), "-2")
	dvbt_nims.insert(1, ("-1", _("auto")))
	if not update:
		config.usage.recording_frontend_priority_dvbt = ConfigSelection(default="-2", choices=dvbt_nims)
	else:
		config.usage.recording_frontend_priority_dvbt.setChoices(dvbt_nims, "-2")
	if not update:
		config.usage.frontend_priority_dvbc = ConfigSelection(default="-2", choices=list(dvbc_nims))
	else:
		config.usage.frontend_priority_dvbc.setChoices(list(dvbc_nims), "-2")
	dvbc_nims.insert(1, ("-1", _("auto")))
	if not update:
		config.usage.recording_frontend_priority_dvbc = ConfigSelection(default="-2", choices=dvbc_nims)
	else:
		config.usage.recording_frontend_priority_dvbc.setChoices(dvbc_nims, "-2")
	if not update:
		config.usage.frontend_priority_atsc = ConfigSelection(default="-2", choices=list(atsc_nims))
	else:
		config.usage.frontend_priority_atsc.setChoices(list(atsc_nims), "-2")
	atsc_nims.insert(1, ("-1", _("auto")))
	if not update:
		config.usage.recording_frontend_priority_atsc = ConfigSelection(default="-2", choices=atsc_nims)
	else:
		config.usage.recording_frontend_priority_atsc.setChoices(atsc_nims, "-2")

	SystemInfo["DVB-S_priority_tuner_available"] = len(dvbs_nims) > 3 and any(len(i) > 2 for i in (dvbt_nims, dvbc_nims, atsc_nims))
	SystemInfo["DVB-T_priority_tuner_available"] = len(dvbt_nims) > 3 and any(len(i) > 2 for i in (dvbs_nims, dvbc_nims, atsc_nims))
	SystemInfo["DVB-C_priority_tuner_available"] = len(dvbc_nims) > 3 and any(len(i) > 2 for i in (dvbs_nims, dvbt_nims, atsc_nims))
	SystemInfo["ATSC_priority_tuner_available"] = len(atsc_nims) > 3 and any(len(i) > 2 for i in (dvbs_nims, dvbc_nims, dvbt_nims))
