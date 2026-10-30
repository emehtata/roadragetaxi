## Nearby Digitraffic readings. The main speed-limit sign remains a separate instrument.
extends PanelContainer
const T := preload('res://i18n.gd')
const WARNINGS := {'133':'congestion', '141':'uneven', '142':'roadworks', '143':'gravel', '144':'slippery',
	'147':'shoulder', '154':'ski', '155':'elk', '156':'reindeer', '165':'lights', '183':'wind', '189':'danger'}
var _header := Label.new()
var _rows: Array[Label] = []

func _ready() -> void:
	z_index = 1  # keep sign readings visible above the movable phone
	var style := StyleBoxFlat.new()
	style.bg_color = Color8(9, 13, 17, 245)
	style.border_color = Color8(172, 130, 45)
	style.set_border_width_all(1)
	style.set_corner_radius_all(4)
	style.set_content_margin_all(8)
	add_theme_stylebox_override('panel', style)
	var column := VBoxContainer.new()
	column.add_theme_constant_override('separation', 2)
	add_child(column)
	_header.add_theme_font_size_override('font_size', 11)
	_header.add_theme_color_override('font_color', Color8(190, 193, 189))
	column.add_child(_header)
	for i in 3:
		var row := Label.new()
		row.add_theme_font_size_override('font_size', 16)
		row.add_theme_color_override('font_color', Color8(255, 195, 70))
		row.clip_text = true
		row.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		column.add_child(row)
		_rows.append(row)
	hide()

static func reading_text(sign: Dictionary, language: String) -> String:
	var speed = sign.get('speed_limit_kmh')
	var parts := PackedStringArray()
	if speed != null:
		parts.append('%d km/h' % int(speed))
	elif str(sign.get('code', '')) != '':
		var code := str(sign['code'])
		parts.append(T.text('electronic_' + WARNINGS[code], language) if WARNINGS.has(code) else T.text('electronic_warning', language) + ' ' + code)
	var route := RegEx.new()
	route.compile('\\[tie_(\\d+)\\]')
	for line in sign.get('text', []):
		parts.append(route.sub(str(line), '[$1]', true))
	return ' · '.join(parts) + '  (%d m)' % int(sign.get('distance_m', 0))

func show_state(signs: Array, language: String) -> void:
	visible = not signs.is_empty()
	_header.text = T.text('electronic_nearby', language) + ' · Digitraffic'
	for i in _rows.size():
		_rows[i].visible = i < signs.size()
		if i < signs.size():
			_rows[i].text = reading_text(signs[i], language)
			_rows[i].tooltip_text = _rows[i].text + '\n' + str(signs[i].get('id', ''))
	tooltip_text = 'Source: Fintraffic / digitraffic.fi, CC BY 4.0'
