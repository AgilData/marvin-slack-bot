import re
import logging
import yaml

crontable = []
outputs = []

user_cache = {}
channel_cache = {}
channel_list = {}

message_list = {}
user_sent_errors = {}

# Change this: This is the ID of the channel where the message will be sent after retrieving from a posting in another
# channel that the bot currently resides.  This can be a series of channels.  These channel names do not start with a
# "#" delimiter.
announce_channels = ["newsletter-content"]

# This is the user ID of the bot, encoded.
bot_user = u'U0X5BL3KJ'

# This function sets up the list of all known channels in Slack.  This gets an initial list of channels; any new channels
# that are made after this bot starts will require this bot to be restarted.
def setup(slack_client):
    logging.debug("Getting list of all known channels from Slack.")
    get_channel_list(slack_client)
    logging.debug("Got %d total channels." % len(channel_list))

    # Announce that we're good to go, since this is the end of the "setup" function
    logging.info("Marvin is now ready to go.  [/_\\]")

# Process the "reaction_added" message, which means a reaction was added to a message by another user.
def process_reaction_added(data, slack_client):
    if data['user'] == bot_user:
        return

    try:
        # Check to see if the reaction was a "+1".  If so, the user gave this post a "thumbs up", which means that they
        # want the URLs that were mentioned to be posted to the channel(s) in the announce_channels array.  If the reaction
        # was a "-1", the message is ignored, and deleted.

        if data['reaction'] == '-1':
            delete_message(slack_client, data['item']['channel'], data['item']['ts'])

        if data['reaction'] == '+1':
            # Pop the message from the stack, as we will never use it again.

            message_entry = message_list.pop(data['item']['ts'])
            mentioned_channel_id = get_channel_id(message_entry['channel_name'])

            delete_message(slack_client, data['item']['channel'], data['item']['ts'])

            for announce_channel in announce_channels:
                channel_id = get_channel_id(announce_channel)

                # Make sure the channel ID doesn't match the current channel from which the message was posted.
                # Otherwise, this will duplicate the posting in the capture channel.

                if channel_id != mentioned_channel_id:
                    if len(message_entry['urls']) == 1:
                        outputs.append([channel_id, "%s mentioned URL %s in channel #%s." % (message_entry['username'], message_entry['urls'][0], message_entry['channel_name'])])
                    else:
                        outputs.append([channel_id, "%s mentioned URLs %s in channel #%s." % (message_entry['username'], message_entry['urls'], message_entry['channel_name'])])

    except:
        # If any errors occur, we catch the error here, and respond back to the user in kind.  Most likely, the
        # user was reacting with a "+1" to a message that was sent earlier, or a response that the bot sent.  Either
        # way, if the reaction was applied to a message that was not saved in the "message_list" hash, we catch
        # the exception here, and send a nice error message back to the user.  But we only send it once.
        # So, we ignore the error.

        return

# Processes any text messages that were received in any of the channels that this bot is a member of.
# "data" is the payload, "slack_client" is the current client connected to the Slack service.
def process_message(data, slack_client):
    # Skip over any posts that have been modified.
    if 'subtype' in data:
        return

    # This is the user ID of the bot.  We chose the name "Marvin", as in Marvin from Hitchhiker's Guide to the Galaxy, or
    # even Marvin the Martian from Looney Tunes - take your pick.
    if data['user'] != bot_user:
        # Fetch the message body
        message = data['text']

        # Fetch the user who sent the message.
        user_id = data['user']
        user = fetch_user(user_id, slack_client)
        username = '%s' % user['name']

        # Channels start with "C".
        if data['channel'].startswith('C'):
            channel = fetch_channel(data['channel'], slack_client)
            channel_name = channel['name']

            # This is a regular expression that parses the message that was sent for any URLs that start with http(s),
            # and loads them into an array.

            urls = re.findall('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', message)

            # For each URL, we will mention the URL that was sent, which user sent it, and from which channel the URL
            # was posted.

            if urls:
                url_list = []

                for url in urls:
                    # Each of the URLs contains a '>' at the end of the URL.  This is how Slack sends the URL in the
                    # message body.  This is cut out of the message, and the URL is stripped of any whitespace.  We
                    # then apply the "str()" function to the URL to convert it from Unicode into a human-readable
                    # string.

                    url_list.append(str(url.split('>', 1)[0].strip()))

                # Originally, this was sending directly to the user who sent the message, but due to testing, we found
                # that this became too chatty.  Several people complained that they were getting "spammed" by the bot.
                # As a result, this became a public message - one that could be reacted to if the user wanted to repost
                # the message.  Logic was added to the "process_reaction_added()" function to prevent multiple users from
                # responding +1 to the message, reposting it multiple times.  The repeat bot will repost once,
                # and never again.

                if len(announce_channels) == 1:
                    message = "I can repost that to #%s for you." % announce_channels[0]
                else:
                    message = "I can repost that to #%s for you." % announce_channels

                message_response = send_message_to_channel(slack_client, data['channel'], message)

                # Messages are reacted upon by their original time signature.  This way, we can keep a cache of previously
                # sent messages, and look them up in the process_reaction_added function.

                time_signature = message_response['ts']
                add_reaction(slack_client, data['channel'], message_response['ts'], 'thumbsup')
                add_reaction(slack_client, data['channel'], message_response['ts'], 'thumbsdown')

                # Create a lookup hash for the message that was sent

                post_data = {}
                post_data['channel_name'] = channel_name
                post_data['urls'] = url_list
                post_data['username'] = username

                # And store it in the lookup table.

                message_list[time_signature] = post_data

        # We *could* process messages that start with a "D" here, which indicate a direct message sent to the bot.

# --- Miscellaneous lookup functions ---

# Looks up a user's real information by their ID.
def fetch_user(user_id, slack_client):
    if not user_cache.has_key(user_id):
        response = slack_client.api_call("users.info", user=user_id)
        user_cache[user_id] = response['user']
    return user_cache[user_id]

# Fetches information for a channel by its ID.
def fetch_channel(channel_id, slack_client):
    if not channel_cache.has_key(channel_id):
        response = slack_client.api_call("channels.info", channel=channel_id)
        channel_cache[channel_id] = response['channel']
    return channel_cache[channel_id]

def delete_message(slack_client, channel, timestamp):
    return slack_client.api_call("chat.delete", channel=channel, ts=timestamp)

# Sends a message directly to the user.  The username must be "@user" format.  (You'll see that formatting throughout
# this module.)
def send_message_to_user(slack_client, username, message):
    return slack_client.api_call("chat.postMessage", channel=username, text=message, username='marvin', as_user='true')

# Sends a message directly to a channel.
def send_message_to_channel(slack_client, channelName, message):
    return slack_client.api_call("chat.postMessage", channel=channelName, text=message, username='marvin', as_user='true')

def add_reaction(slack_client, channelName, timestamp, reactionName):
    return slack_client.api_call("reactions.add", channel=channelName, timestamp=timestamp, name=reactionName)

# Right-chops a string matching an ending string.
def rchop(thestring, ending):
    if thestring.endswith(ending):
        return thestring[:-len(ending)]
    return thestring

# Gets a list of all channels on the Slack server this bot is a member of.
def get_channel_list(slack_client):
    response = slack_client.api_call("channels.list")
    for channel in response['channels']:
        channel_list[channel['name']] = channel['id']

# Retrieves a channel ID by name from a lookup table.  This lookup table is formed using "get_channel_list()"
def get_channel_id(channel_name):
    return channel_list[channel_name]
