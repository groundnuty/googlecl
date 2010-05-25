"""
Service details and instances for the Picasa service.

Some use cases:
Add event:
  calendar add "Lunch with Tony on Tuesday at 12:00" 

List events for today:
  calendar today
  
Created on May 24, 2010

@author: Tom Miller

"""
import gdata.calendar.service
import util
import calendar


class CalendarServiceCL(gdata.calendar.service.CalendarService,
                        util.BaseServiceCL):

  def __init__(self, regex=False, tags_prompt=False, delete_prompt=True):
    """Constructor.
    
    Keyword arguments:
      regex: Indicates if regular expressions should be used for matching
             strings, such as album titles. (Default False)
      tags_prompt: Indicates if while inserting photos, instance should prompt
                   for tags for each photo. (Default False)
      delete_prompt: Indicates if instance should prompt user before
                     deleting an album or photo. (Default True)
              
    """
    gdata.calendar.service.CalendarService.__init__(self)
    util.BaseServiceCL.set_params(self, regex, tags_prompt, delete_prompt)

  def quick_add_event(self, quick_add_string):
    """Add an event using the Calendar Quick Add feature.
    
    Keyword arguments:
      quick_add_string: String to be parsed by the Calendar service, as if it
                        was entered via the "Quick Add" function.

    Returns:
      The event that was added.
    
    """
    import atom
    event = gdata.calendar.CalendarEventEntry()
    event.content = atom.Content(text=quick_add_string)
    event.quick_add = gdata.calendar.QuickAdd(value='true') 
    return self.InsertEvent(event, '/calendar/feeds/default/private/full')

  QuickAddEvent = quick_add_event

  def get_events(self, start_date, end_date, title):
    """Get events that fall within a date range."""
    query = gdata.calendar.service.CalendarEventQuery('default', 'private',
                                                      'full')
    query.start_min = start_date
    query.start_max = end_date 
    return self.GetEntries(query.ToUri(), title,
                           converter=gdata.calendar.CalendarEventFeedFromString)

  GetEvents = get_events

  def is_token_valid(self):
    """Check that the token being used is valid."""
    return util.BaseServiceCL.IsTokenValid(self,
                                    '/calendar/feeds/default/allcalendars/full')

  IsTokenValid = is_token_valid


service_class = CalendarServiceCL


#===============================================================================
# Each of the following _run_* functions execute a particular task.
#  
# Keyword arguments:
#  client: Client to the service being used.
#  options: Contains all attributes required to perform the task
#  args: Additional arguments passed in on the command line, may or may not be
#        required
#===============================================================================
def _run_list(client, options, args):
  from_, junk, to = options.date.partition(',')
  entries = client.get_events(from_, to, options.title)
  if args:
    style_list = args[0].split(',')
  else:
    style_list = util.get_config_option(calendar.SECTION_HEADER,
                                        'list_style').split(',')
  for e in entries:
    print util.entry_to_string(e, style_list, delimiter=options.delimiter)
 

def _run_add(client, options, args):
  client.quick_add_event(args[0])


tasks = {'list': util.Task('List events for a date range', callback=_run_list,
                           required=['delimiter', 'date'], optional='title'),
         'today': util.Task('List events for today',
                            required='delimiter', optional='title'),
         'add': util.Task('Add event to calendar', callback=_run_add,
                          args_desc='QUICK_ADD_TEXT')}