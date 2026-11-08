/**
 * The drift pin for the Zibo layout (issue #253): every `control_id` the catalog under
 * `adapters/xplane/cockpit_catalogs/zibo-b738/*.yaml` published when this layout was
 * drawn — 73 live + 20 parked, grouped by panel, in catalog order. The layout tests assert
 * that every id here is placed on its panel or listed as `unplaced`, and that no slot
 * names an id outside this list. The list is checked in by hand on purpose: the YAML
 * lives outside `ui/`, and a control that appears live but is missing here still renders
 * in the "Not on the diagram" strip — drift degrades to a visible gap, never a crash.
 */

export const ZIBO_MCP_IDS = [
  'fd_capt',
  'fd_fo',
  'cmd_a',
  'cmd_b',
  'ap_disconnect',
  'hdg_sel',
  'vorloc',
  'app',
  'mcp_alt',
  'mcp_hdg',
  'mcp_speed',
  // parked
  'mcp_vs',
  'ias_mach_changeover',
  'lnav',
] as const;

export const ZIBO_OVERHEAD_IDS = [
  'gen1',
  'gen2',
  'apu_gen1',
  'apu_gen2',
  'apu_master',
  'apu_bleed',
  'ext_power',
  'fuel_pump_l1',
  'fuel_pump_l2',
  'fuel_pump_r1',
  'fuel_pump_r2',
  'fuel_pump_c1',
  'fuel_pump_c2',
  'fuel_crossfeed',
  'hyd_eng1_pump',
  'hyd_eng2_pump',
  'hyd_elec1_pump',
  'hyd_elec2_pump',
  'window_heat_l_side',
  'window_heat_l_fwd',
  'window_heat_r_side',
  'window_heat_r_fwd',
  'probe_heat_capt',
  'probe_heat_fo',
  'wing_anti_ice',
  'eng1_anti_ice',
  'eng2_anti_ice',
  'bleed_eng1',
  'bleed_eng2',
  'iso_valve',
  'pack_l',
  'pack_r',
  // parked
  'battery',
  'standby_power',
  'gen_drive_disc1',
  'gen_drive_disc2',
  'bus_transfer',
  'irs_l',
  'irs_r',
] as const;

export const ZIBO_PEDESTAL_IDS = [
  'flaps_lever',
  'speedbrake_lever',
  'speedbrake_arm',
  'parking_brake',
  'stab_trim',
  'rudder_trim',
  'aileron_trim',
  'stab_trim_cutout_main',
  'stab_trim_cutout_autopilot',
  'transponder_mode',
  'transponder_ident',
  'transponder_atc',
  'nav1_swap',
  'nav2_swap',
  'com1_standby_freq',
  'com1_swap',
  'com2_standby_freq',
  'com2_swap',
  'transponder_code',
  // parked
  'start_lever_1',
  'start_lever_2',
  'toga_left',
  'toga_right',
  'at_disconnect_left',
  'at_disconnect_right',
  'horn_cutout',
  'weather_radar_wxr',
  'com_rtp_panel',
] as const;

export const ZIBO_LIGHTS_IDS = [
  'landing_lights_left',
  'landing_lights_right',
  'rwy_turnoff_left',
  'rwy_turnoff_right',
  'logo_light',
  'wing_light',
  'wheel_well_light',
  'taxi_light',
  'position_light',
  'cockpit_dome',
  'anti_collision_beacon',
  // parked
  'strobe_light',
] as const;

/** All 93 ids, mcp → overhead → pedestal → lights. */
export const ZIBO_CONTROL_IDS: readonly string[] = [
  ...ZIBO_MCP_IDS,
  ...ZIBO_OVERHEAD_IDS,
  ...ZIBO_PEDESTAL_IDS,
  ...ZIBO_LIGHTS_IDS,
];
