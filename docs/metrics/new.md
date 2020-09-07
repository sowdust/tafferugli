---
layout: page
title: Extend metrics
nav_order: 2
parent: Metrics
description: "Implement new metrics."
permalink: /metrics/new
---


## Extend metrics

It should be quite simple to extend metrics implementing your own.

If you do, please [share your metrics](/contribute) with the community : )


### Basic metric

Metrics are implemented as Python classes in the file ```models/metrics.py``` and **must** respect the following properties:

 - name must start with ```Metric```
 - must have the following properties:
    - ```description```: a brief text on what the metrics does
    - ```target_type```: a choice specifying the type of the target (one among ```TARGET_USERS```, ```TARGET_TWEETS```, ```TARGET_ANY```, ```TARGET_BOTHS```)
 - must overwrite the method ```computation()```, which returns ```True```  when the computation ends withouth errors

Each Metric class, by default, depending on its ```target_type```, has the attributes ```tweets``` and/or ```twitter_users```, that are Django Querysets objects of type ```Tweet``` and/or ```TwitterUser```. By default, they contain the **selection** target on which the metric was executed (alteratively, if executed campaign-wide, they contain all tweets/users linked to a campaign). 

After you have implemented your Metric, the database need to be updated. To do so, run:

```bash
python manage.py makemigrations
python manage.py migrate
```

If you want to be able to manege your metric from the Django default admin application, remember to register it in the ```admin.py``` file.

### More options

Metrics can be highly customised. Have a look at the code to learn how; if you need help, [get in contact](/contact)

Some common customisation might be:


 - make a custom result page:
     - add a template file in ```templates/metrics``` 
     - override the ```template_file``` attribute, pointing to your custom template
 - add custom parameters:
     - create a form adding a template in ```templates/metrics/forms``` 
     - override the ```template_form``` attribute, pointing to your form template file
     - override the ```method set_params_from_req``` to **check** and set your custom parameters
     - add a template file in ```templates/custom_fields``` to show the custom field values in the metric output page
     - override the ```template_form``` attribute, pointing to your custom code

If your metric need to perform some potentially long background operation that should not keep other metrics to run, you can add an ```Operation``` class to the ```models/operations.py``` file. See the code of 
```MetricGraphCommunityNetwork``` for an example.


