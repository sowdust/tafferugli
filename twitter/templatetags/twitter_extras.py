import re 
from django import template
from django.utils import timezone
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.html import escape


register = template.Library()

@register.filter
def highlight(text, word):
	insensitive = re.compile(re.escape(word), re.IGNORECASE)
	matches = re.findall(insensitive, text)
	for match in matches:
		text = text.replace(match, '<mark>%s</mark>' % match)
	return mark_safe(text)

@register.filter
def profile_image_resize(original, size=''):
	return original.replace('_normal',size)
	
@register.filter
def make_status_link(id_str, text):
	return mark_safe('<a href="https://twitter.com/i/web/status/%s" target="_blank">%s</a>' % (id_str,text))

@register.filter
def counter_update(obj_id,args):
	what, type = args.split(',')
	script = """
	<span class="counter" id="counter_""" + what + """_""" + type + """_""" + str(obj_id) + """">...</span>
	<script>
		//update_counter('#counter_""" + what + """_""" + type + """_""" + str(obj_id) + """','""" + what + """','""" + type + """','""" + str(obj_id) + """');
		setInterval(function(){
			update_counter('#counter_""" + what + """_""" + type + """_""" + str(obj_id) + """','""" + what + """','""" + type + """','""" + str(obj_id) + """');
		},7000);
	</script>
	"""
	return mark_safe(script)

@register.filter
def distribution_chart(distribution):

	string_daily ="""<script>
var ctx = document.getElementById('{css_id}').getContext('2d');
var myChart = new Chart(ctx, {{
    type: '{chart_style}',
    data: {{
        labels: [{labels}],
        datasets: [{{
            label: '{frequency_label} distribution',
            data: [{data_points}],
                lineTension: 0,
			    backgroundColor: 'transparent',
	            borderColor: 'rgba(255, 99, 132, 1)',
			    borderWidth: 4,
			    pointBackgroundColor: 'rgba(255, 99, 132, 1)'
        }}]
    }},
    options: {{
        scales: {{
            yAxes: [{{
                ticks: {{
                    beginAtZero: true
                }}
            }}]
        }},
	  legend: {{
	    display: false,
	  }}
    }}
}});
</script>"""

	string_weekly ="""<script>
var ctx = document.getElementById('{css_id}').getContext('2d');
var myChart = new Chart(ctx, {{
    type: '{chart_style}',
    data: {{
        labels: [{labels}],
        datasets: [{{
            label: '{frequency_label} distribution',
            data: [{data_points}],
            backgroundColor: 'rgba(255, 99, 132, 0.2)',
            borderColor: 'rgba(255, 99, 132, 1)',
            borderWidth: 1
        }}]
    }},
    options: {{
        scales: {{
            yAxes: [{{
                ticks: {{
                    beginAtZero: true
                }}
            }}]
        }},
	  legend: {{
	    display: false,
	  }}
    }}
}});
</script>"""

	weekdays = ['"Sunday"', '"Monday"', '"Tuesday"', '"Wednesday"', '"Thursday"', '"Friday"', '"Saturday"']

	if distribution.frequency == 'w':
		data_points = ','.join(str(x) for x in distribution.labeled_data_points.values_list('counter',flat=True))
		labels = ','.join(str(weekdays[x-1]) for x in distribution.labeled_data_points.values_list('label',flat=True))
		frequency_label = 'weekly'
		css_id = 'myChartWeekly'
		chart_style = 'horizontalBar'
		string = string_weekly
	elif distribution.frequency == 'h':
		data_points = ','.join(str(x) for x in distribution.labeled_data_points.values_list('counter',flat=True))
		labels = ','.join('"%s"' % x for x in distribution.labeled_data_points.values_list('label',flat=True))
		frequency_label = 'hourly'
		css_id = 'myChartHourly'
		chart_style = 'bar'
		string = string_weekly

	elif distribution.frequency == 'd':
		data_points = ','.join(str(x) for x in distribution.dated_data_points.values_list('counter',flat=True))
		labels = ','.join('"%s"' % x.strftime('%Y-%m-%d') for x in distribution.dated_data_points.values_list('date',flat=True))
		frequency_label = 'daily'
		css_id = 'myChartDaily'
		chart_style = 'line'
		string = string_daily
	else:
		return ''

	string = string.format(
		chart_style=chart_style,
		css_id=css_id,
		labels=labels,
		frequency_label=frequency_label,
		data_points=data_points
	)

	return mark_safe(string)




@register.filter
def creation_date_distribution_chart(distribution):

	string_daily ="""<script>
var ctx = document.getElementById('{css_id}').getContext('2d');
var myChart = new Chart(ctx, {{
    type: '{chart_style}',
    data: {{
        labels: [{labels}],
        datasets: [{{
            label: '{frequency_label} distribution',
            data: [{data_points}],
                lineTension: 0,
			    backgroundColor: 'transparent',
	            borderColor: 'rgba(255, 99, 132, 1)',
			    borderWidth: 4,
			    pointBackgroundColor: 'rgba(255, 99, 132, 1)'
        }}]
    }},
    options: {{
        scales: {{
            yAxes: [{{
                ticks: {{
                    beginAtZero: true
                }}
            }}]
        }},
	  legend: {{
	    display: false,
	  }}
    }}
}});
</script>"""

	data_points = ','.join(str(x) for x in distribution.dated_data_points.values_list('counter',flat=True))
	labels = ','.join('"%s"' % x.strftime('%Y-%m-%d') for x in distribution.dated_data_points.values_list('date',flat=True))
	frequency_label = 'daily'
	css_id = 'creationDateChart'
	chart_style = 'bar'
	string = string_daily

	string = string.format(
		chart_style=chart_style,
		css_id=css_id,
		labels=labels,
		frequency_label=frequency_label,
		data_points=data_points
	)

	return mark_safe(string)






@register.filter
def tweets_table(tweets,parameter=None):

	form = True
	highlight_term = None

	if parameter is not None:
		if parameter == False or parameter == True:
			form = parameter
		else:
			highlight_term = parameter


	str = """
	<a name="TweetsTable"></a>
	<div class="card">
	<div class="table-responsive p-3">
	<table class="table table-sm  table-hover" id="tweets_table">
	  <thead>
	    <tr>"""

	if form:
		str += '<th scope="col"><input type="checkbox" id="select_all_checkboxes" checked></th>'

	str += """
	      <th scope="col">Created</th>
	      <th scope="col">ID</th>
	      <th scope="col">Author</th>
	      <th scope="col">Tweet</th>
	      <th scope="col">Location</th>
	      <th scope="col"><abbr title="This number refers to the replies at the moment in which the tweet was stored">Replies</abbr></th>
	      <th scope="col"><abbr title="This number refers to the retweets at the moment in which the tweet was stored">Retweets</abbr></th>
	      <th scope="col"><abbr title="This number refers to the favorites at the moment in which the tweet was stored">Favorites</abbr></th>
	      <th scope="col"><abbr title="Datacenter id extracted from tweet id">DC</abbr></th>
	      <th scope="col"><abbr title="Server id extracted from tweet id">SRV</abbr></th>
	      <th scope="col"><abbr title="Sequence number as extracted from tweet id">SN</abbr></th>
	      <th scope="col">Link</th>      
	    </tr>
	  </thead>
	  <tbody>"""

	for tweet in tweets:
		str += '<tr>'
		if form:
			str += '<td><input type="checkbox" name="tweets" value="%s" checked></td>' % tweet.id_str

		str += """
		  <td>{created_at}</td>
		  <td><a href="{tweet_url}">{tweet_id}</a></td>
	      <td><a href="{author_url}">{screen_name}</a></td>
	      <td>{highlighted_text}</td>
	      <td>{location}</td>
	      <td>{replies}</td>
	      <td>{retweets}</td>
	      <td>{favorites}</td>
	      <td>{fromid_datacentrenum}</td>
	      <td>{fromid_servernum}</td>
	      <td>{fromid_sequence}</td>
	      <td><a href="javascript:;" onclick="javascript:link_external_website('{twitter_url}')"> go </a> </td>
	    </tr>
	    """.format(
			tweet_url = tweet.get_absolute_url(),
			created_at = tweet.created_at.strftime('%Y-%m-%d %H:%M'),
			tweet_id = tweet.id_str,
	    	author_url = tweet.author.get_absolute_url(),
	    	screen_name=escape(tweet.author.screen_name),
	    	highlighted_text=highlight(escape(tweet.text),highlight_term) if highlight_term else escape(tweet.text),
			location = tweet.location if tweet.location is not None else '-',
			replies = tweet.reply_count,
			retweets=tweet.retweet_count,
			favorites=tweet.favorite_count,
			fromid_datacentrenum=tweet.fromid_datacentrenum,
	    	fromid_servernum=tweet.fromid_servernum,
	    	fromid_sequence=tweet.fromid_sequencenum,
	    	twitter_url=tweet.get_twitter_url())
	str += """
	  </tbody>
	</table>
	</div>
	</div>
	"""
	return mark_safe(str)

@register.filter
def twitter_users_table(twitter_users,form=False):
	str = """
	<a name="TwitterUsersTable"></a>
	<div class="table-responsive p-3">
	<table class="table table-sm table-hover" id="twitter_users_table" style="overflow-x:hidden">
	  <thead>
	    <tr>"""

	if form:
		str += '<th scope="col"><input type="checkbox" id="select_all_checkboxes" checked></th>'

	str += """
	      <th scope="col">ID</th>
	      <th scope="col">Screen Name</th>
	      <th scope="col">Name</th>
	      <th scope="col">Location</th>      
	      <th scope="col">Followers</th>
	      <th scope="col">Friends</th>
	      <th scope="col">Favs</th>
	      <th scope="col">Statuses</th>
	      <th scope="col">Created</th>	            
	      <th scope="col">Twitter</th>	            
	    </tr>
	  </thead>
	  <tbody>"""


	for u in twitter_users:
		str += '<tr>'

		if form:
			str += '<td><input type="checkbox" name="uid" value="%s" checked></td>' % u.id_str

		if not u.filled:
			str += """
			  <td><a href="{url}">{id_str}</a></td>
			  <td>{screen_name}</td>
			  <td>{name}</td>
			  <td>-</td>
			  <td>-</td>
			  <td>-</td>
			  <td>-</td>
			  <td>-</td>
			  <td>-</td>
			  <td><a href="{twitter_url}" target="_blank">Link</a></td>
			</tr>
			""".format(
				url=u.get_absolute_url(),
				id_str=escape(u.id_str),
				screen_name=escape(u.screen_name),
				name=escape(u.name),
				twitter_url=u.get_twitter_url())
		else:

			str += """
			  <td><a href="{url}">{id_str}</a></td>
			  <td>{screen_name}</td>
			  <td>{name}</td>
			  <td>{location}</td>
			  <td>{followers_count}</td>
			  <td>{friends_count}</td>
			  <td>{favourites_count}</td>
			  <td>{statuses_count}</td>
			  <td>{created_at}</td>
			  <td><a href="{twitter_url}" target="_blank">Link</a></td>
			</tr>
			""".format(
				url=u.get_absolute_url(),
				id_str=u.id_str,
				screen_name=escape(u.screen_name),
				name=escape(u.name),
				location=escape(u.location) if u.location is not None else '-',
				followers_count=int(u.followers_count),
				friends_count=int(u.friends_count),
				favourites_count=int(u.favourites_count),
				statuses_count=int(u.statuses_count),
				created_at=escape(u.created_at),
				twitter_url=u.get_twitter_url())
	str += """
	  </tbody>
	</table>
	</div>
	"""
	return mark_safe(str)

@register.filter
def sources_pie(sources_counted):

	sources_counted = sources_counted[:15]
	data_str = ''
	for s in sources_counted:
		data_str += 'data["%s"] = %s;\n' % (s['name'],s['counter'])
	domain_str = ','.join(['"%s"' % s['name'] for s in sources_counted])

	ret = """
	<div id="sources_pie"></div>
	<script>
		// set the dimensions and margins of the graph
		var width = 600
			height = 400
			//margin = 150
			
		var margin = {top: 20, right: 90, bottom: 20, left: 20}
		//var radius = Math.min(width, height) / 2 - margin.right
		//var radius = Math.min(width-margin.top, height-margin.right) / 2 
		var radius = width / 2 - margin.right
		
		var svg = d3.select("#sources_pie")
		  .append("svg")
			.attr("width", width)
			.attr("height", height)
		  .append("g")
			.attr("transform", "translate(" + (width / 2 - margin.right + margin.left) + "," + height / 2 + ")");
		
		// Create dummy data
		var data = {}
		""" + data_str + """
		
		// set the color scale
		var color = d3.scaleOrdinal()
		  .domain([""" + domain_str + """])
		  .range(d3.schemeDark2);
		
		// Compute the position of each group on the pie:
		var pie = d3.pie()
		  .sort(null) // Do not sort group by size
		  .value(function(d) {return d.value; })
		var data_ready = pie(d3.entries(data))
		
		// The arc generator
		var arc = d3.arc()
		  .innerRadius(radius * 0.5)         // This is the size of the donut hole
		  .outerRadius(radius * 0.8)
		
		// Another arc that won't be drawn. Just for labels positioning
		/*
		var outerArc = d3.arc()
		  .innerRadius(radius * 0.9)
		  .outerRadius(radius * 0.9)
		  */
				
		// Build the pie chart: Basically, each part of the pie is a path that we build using the arc function.
		svg
		  .selectAll('allSlices')
		  .data(data_ready)
		  .enter()
		  .append('path')
		  .attr('d', arc)
		  .attr('data-legend',function(d) { return 'aaaa'})
		  .attr('fill', function(d){ return(color(d.data.key)) })
		  .attr("stroke", "white")
		  .style("stroke-width", "1px")
		  .style("opacity", 0.7)
		
		// Add the polylines between chart and labels:
		/*   --- using side legend instead
		svg
		  .selectAll('allPolylines')
		  .data(data_ready)
		  .enter()
		  .append('polyline')
			.attr("stroke", "white")
			.style("fill", "none")
			.attr("stroke-width", 1)
			.attr('points', function(d) {
			  var posA = arc.centroid(d) // line insertion in the slice
			  var posB = outerArc.centroid(d) // line break: we use the other arc generator that has been built only for that
			  var posC = outerArc.centroid(d); // Label position = almost the same as posB
			  var midangle = d.startAngle + (d.endAngle - d.startAngle) / 2 // we need the angle to see if the X position will be at the extreme right or extreme left
			  posC[0] = radius * 0.95 * (midangle < Math.PI ? 1 : -1); // multiply by 1 or -1 to put it on the right or on the left
			  return [posA, posB, posC]
			})
		
		// Add the polylines between chart and labels:
		svg
		  .selectAll('allLabels')
		  .data(data_ready)
		  .enter()
		  .append('text')
			.text(function(d) {
			    if(d.endAngle - d.startAngle<4*Math.PI/180){return ""}
    			return d.data.key;
    		})
			.attr("fill", "white")
			.attr("font-size", "12px")
			.attr('transform', function(d) {
				var pos = outerArc.centroid(d);
				var midangle = d.startAngle + (d.endAngle - d.startAngle) / 2
				pos[0] = radius * 0.99 * (midangle < Math.PI ? 1 : -1);
				return 'translate(' + pos + ')';
			})
			.style('text-anchor', function(d) {
				var midangle = d.startAngle + (d.endAngle - d.startAngle) / 2
				return (midangle < Math.PI ? 'start' : 'end')
			})
			*/
			
		svg.append("g")
		  .attr("class", "legendOrdinal")
		  .attr("fill", "white")
		  .attr("transform", "translate(180,-180)")
		  .attr("font-size", "12px");
		
		var legendOrdinal = d3.legendColor()
		  //d3 symbol creates a path-string, for example
		  //"M0,-8.059274488676564L9.306048591020996,
		  //8.059274488676564 -9.306048591020996,8.059274488676564Z"
		  .shape("path", d3.symbol().type(d3.symbolSquare).size(150)())
		  .shapePadding(10)
		  //use cellFilter to hide the "e" cell
		  //.cellFilter(function(d){ return d.label !== "e" })
		  .scale(color);
		
		svg.select(".legendOrdinal")
		  .call(legendOrdinal);


		</script>
	"""
	return mark_safe(ret)

@register.filter
def domains_lollipop(domains):

	str_domains = ''
	max_counter = 0
	domains = domains[:20]
	for d in domains:
		str_domains += 'data.push({domain: \'%s\',counter: %d});' % (d['hostname'],d['counter'])
		max_counter = d['counter'] if d['counter'] > max_counter else max_counter


	ret = """
	<div id="domains_lollipop"></div>
	<script>
	// set the dimensions and margins of the graph
	var margin = {top: 10, right: 30, bottom: 40, left: 100},
		width = 600 - margin.left - margin.right,
		height = 400 - margin.top - margin.bottom;
	
	// append the svg object to the body of the page
	var svg = d3.select("#domains_lollipop")
	  .append("svg")
		.attr("width", width + margin.left + margin.right)
		.attr("height", height + margin.top + margin.bottom)
	  .append("g")
		.attr("transform",
			  "translate(" + margin.left + "," + margin.top + ")");
	
	// Parse the Data
	data  = [];
	""" + str_domains + """
	
	  // Add X axis
	  var x = d3.scaleLinear()
		.domain([0, """ +  str(max_counter) + """])
		.range([ 0, width]);
	  svg.append("g")
		.attr("transform", "translate(0," + height + ")")
		.call(d3.axisBottom(x))
		.selectAll("text")
		  .attr("transform", "translate(-10,0)rotate(-45)")
		  .style("text-anchor", "end");
	
	// Y axis
	var y = d3.scaleBand()
	  .range([ 0, height ])
	  .domain(data.map(function(d) { return d.domain; }))
	  .padding(1);
	svg.append("g")
	  .call(d3.axisLeft(y))
	
	
	// Lines
	svg.selectAll("myline")
	  .data(data)
	  .enter()
	  .append("line")
		.attr("x1", function(d) { return x(d.counter); })
		.attr("x2", x(0))
		.attr("y1", function(d) { return y(d.domain); })
		.attr("y2", function(d) { return y(d.domain); })
		.attr("stroke", "grey")
	
	// Circles
	svg.selectAll("mycircle")
	  .data(data)
	  .enter()
	  .append("circle")
		.attr("cx", function(d) { return x(d.counter); })
		.attr("cy", function(d) { return y(d.domain); })
		.attr("r", "4")
		.style("fill", "#69b3a2")
		.attr("stroke", "black")
	</script>
	"""
	return mark_safe(ret)

@register.filter
def wordcloud(hashtags):

	js_words = ",".join(['"%s"' % h.text for h in hashtags])

	str = """
	<div id="word_cloud"></div>
	<script>
	
	// List of words
	var myWords = [""" + js_words + """];
	var frequencies = {};
	"""

	try:
		for h in hashtags:
			str += """frequencies['{text}'] = {counter};
			""".format(
				text=h.text,
				counter=h.counter
			)
	except:
		str +="""
		for (var i = 0; i < myWords.length; i++) {
			var w = myWords[i];
			frequencies[w] = frequencies[w] ? frequencies[w] + 1 : 1;
		}"""

	str +="""

		var max_freq = d3.max(myWords, function(d) { return frequencies[d];});
		
		var size_scale = d3.scaleLinear()
			//.base(max_freq)
			.domain([1, max_freq])
			.range([10, 100]);
			
		function get_word_size(word) {
			var size = Math.round(size_scale(frequencies[word.text]));		
			return size;
		}

	// Fill colors
	var fill =  function(i) {
		return d3.schemeCategory10[i % 10];
	}
	
	// set the dimensions and margins of the graph
	var margin = {top: 10, right: 10, bottom: 10, left: 10},
		width = 600 - margin.left - margin.right,
		height = 400 - margin.top - margin.bottom;
	
	// append the svg object to the body of the page
	var svg = d3.select("#word_cloud").append("svg")
		.attr("width", width + margin.left + margin.right)
		.attr("height", height + margin.top + margin.bottom)
	  .append("g")
		.attr("transform",
			  "translate(" + margin.left + "," + margin.top + ")");
	
	// Constructs a new cloud layout instance. It run an algorithm to find the position of words that suits your requirements
	// Wordcloud features that are different from one word to the other must be here
	var layout = d3.layout.cloud()
	  .size([width, height])
	  .words(myWords.map(function(d) {
		  return {text: d, size: frequencies[d] };
		}))
	  .padding(5)        //space between words
	  //.rotate(function() { return ~~(Math.random() * 2) * 90; })      // rotation angle in degrees
	  .rotate(function(d) { return 0} )
	  .font("monospace")
	  .fontSize(function(d) { return get_word_size(d); })      // font size of words
	  .spiral("archimedean")
	  .on("end", draw);
	layout.start();
	
	// This function takes the output of 'layout' above and draw the words
	// Wordcloud features that are THE SAME from one word to the other can be here
	function draw(words) {
	  svg
		.append("g")
		  .attr("transform", "translate(" + layout.size()[0] / 2 + "," + layout.size()[1] / 2 + ")")
		  .selectAll("text")
			.data(words)
		  .enter().append("text")
			.style("font-size", function(d) { return get_word_size(d) + "px"; })
			.style("fill", function(d, i) { return fill(i); })
			.attr("text-anchor", "middle")
			.style("font-family", "monospace")
			.attr("text-anchor", "middle")
			.attr("transform", function(d) {
			  return "translate(" + [d.x, d.y] + ")rotate(" + d.rotate + ")";
			})
			.text(function(d) { return d.text; });
	}
	</script>
	"""
	return mark_safe(str)