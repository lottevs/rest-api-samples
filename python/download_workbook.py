####
# This script contains functions that demonstrate how to publish
# a workbook using the Tableau Server REST API. It will publish a
# specified workbook to the 'default' project of a given server.
#
# Note: The REST API publish process cannot automatically include
# extracts or other resources that the workbook uses. Therefore,
# a .twb file with data from a local computer cannot be published.
# For simplicity, this sample will only accept a .twbx file to publish.
#
# For more information, refer to the documentations on 'Publish Workbook'
# (https://onlinehelp.tableau.com/current/api/rest_api/en-us/help.htm)
#
# To run the script, you must have installed Python 2.7.9 or later,
# plus the 'requests' library:
#   http://docs.python-requests.org/en/latest/
#
# The script takes in the server address and username as arguments,
# where the server address has no trailing slash (e.g. http://localhost).
# Run the script in terminal by entering:
#   python publish_sample.py <server_address> <username>
#
# When running the script, it will prompt for the following:
# 'Workbook file to publish': Enter file path to the desired workbook file
#                             to publish (.twbx file).
# 'Password':                 Enter password for the user to log in as.
####

from version import VERSION
import requests # Contains methods used to make HTTP requests
import xml.etree.ElementTree as ET # Contains methods used to build and parse XML
import sys
import os
import math
import getpass
import re
import zipfile

# The following packages are used to build a multi-part/mixed request.
# They are contained in the 'requests' library
from requests.packages.urllib3.fields import RequestField
from requests.packages.urllib3.filepost import encode_multipart_formdata

# The namespace for the REST API is 'http://tableausoftware.com/api' for Tableau Server 9.0
# or 'http://tableau.com/api' for Tableau Server 9.1 or later
xmlns = {'t': 'http://tableau.com/api'}

# The maximum size of a file that can be published in a single request is 64MB
#FILESIZE_LIMIT = 1024 * 1024 * 64   # 64MB

# For when a workbook is over 64MB, break it into 5MB(standard chunk size) chunks
#CHUNK_SIZE = 1024 * 1024 * 5    # 5MB

# If using python version 3.x, 'raw_input()' is changed to 'input()'
if sys.version[0] == '3': raw_input=input


class ApiCallError(Exception):
    pass


class UserDefinedFieldError(Exception):
    pass


def _encode_for_display(text):
    """
    Encodes strings so they can display as ASCII in a Windows terminal window.
    This function also encodes strings for processing by xml.etree.ElementTree functions. 
    
    Returns an ASCII-encoded version of the text.
    Unicode characters are converted to ASCII placeholders (for example, "?").
    """
    return text.encode('ascii', errors="backslashreplace").decode('utf-8')


# def _make_multipart(parts):
    # """
    # Creates one "chunk" for a multi-part upload

    # 'parts' is a dictionary that provides key-value pairs of the format name: (filename, body, content_type).

    # Returns the post body and the content type string.

    # For more information, see this post:
        # http://stackoverflow.com/questions/26299889/how-to-post-multipart-list-of-json-xml-files-using-python-requests
    # """
    # mime_multipart_parts = []
    # for name, (filename, blob, content_type) in parts.items():
        # multipart_part = RequestField(name=name, data=blob, filename=filename)
        # multipart_part.make_multipart(content_type=content_type)
        # mime_multipart_parts.append(multipart_part)

    # post_body, content_type = encode_multipart_formdata(mime_multipart_parts)
    # content_type = ''.join(('multipart/mixed',) + content_type.partition(';')[1:])
    # return post_body, content_type


def _check_status(server_response, success_code):
    """
    Checks the server response for possible errors.

    'server_response'       the response received from the server
    'success_code'          the expected success code for the response
    Throws an ApiCallError exception if the API call fails.
    """
    if server_response.status_code != success_code:
        parsed_response = ET.fromstring(server_response.text)

        # Obtain the 3 xml tags from the response: error, summary, and detail tags
        error_element = parsed_response.find('t:error', namespaces=xmlns)
        summary_element = parsed_response.find('.//t:summary', namespaces=xmlns)
        detail_element = parsed_response.find('.//t:detail', namespaces=xmlns)

        # Retrieve the error code, summary, and detail if the response contains them
        code = error_element.get('code', 'unknown') if error_element is not None else 'unknown code'
        summary = summary_element.text if summary_element is not None else 'unknown summary'
        detail = detail_element.text if detail_element is not None else 'unknown detail'
        error_message = '{0}: {1} - {2}'.format(code, summary, detail)
        raise ApiCallError(error_message)
    return


def sign_in(server, username, password, site=""):
    """
    Signs in to the server specified with the given credentials

    'server'   specified server address
    'username' is the name (not ID) of the user to sign in as.
               Note that most of the functions in this example require that the user
               have server administrator permissions.
    'password' is the password for the user.
    'site'     is the ID (as a string) of the site on the server to sign in to. The
               default is "", which signs in to the default site.
    Returns the authentication token and the site ID.
    """
    url = server + "/api/{0}/auth/signin".format(VERSION)

    # Builds the request
    xml_request = ET.Element('tsRequest')
    credentials_element = ET.SubElement(xml_request, 'credentials', name=username, password=password)
    ET.SubElement(credentials_element, 'site', contentUrl=site)
    xml_request = ET.tostring(xml_request)

    # Make the request to server
    server_response = requests.post(url, data=xml_request)
    _check_status(server_response, 200)

    # ASCII encode server response to enable displaying to console
    server_response = _encode_for_display(server_response.text)

    # Reads and parses the response
    parsed_response = ET.fromstring(server_response)

    # Gets the auth token and site ID
    token = parsed_response.find('t:credentials', namespaces=xmlns).get('token')
    site_id = parsed_response.find('.//t:site', namespaces=xmlns).get('id')
    return token, site_id


def sign_out(server, auth_token):
    """
    Destroys the active session and invalidates authentication token.

    'server'        specified server address
    'auth_token'    authentication token that grants user access to API calls
    """
    url = server + "/api/{0}/auth/signout".format(VERSION)
    server_response = requests.post(url, headers={'x-tableau-auth': auth_token})
    _check_status(server_response, 204)
    return


# def start_upload_session(server, auth_token, site_id):
    # """
    # Creates a POST request that initiates a file upload session.

    # 'server'        specified server address
    # 'auth_token'    authentication token that grants user access to API calls
    # 'site_id'       ID of the site that the user is signed into
    # Returns a session ID that is used by subsequent functions to identify the upload session.
    # """
    # url = server + "/api/{0}/sites/{1}/fileUploads".format(VERSION, site_id)
    # server_response = requests.post(url, headers={'x-tableau-auth': auth_token})
    # _check_status(server_response, 201)
    # xml_response = ET.fromstring(_encode_for_display(server_response.text))
    # return xml_response.find('t:fileUpload', namespaces=xmlns).get('uploadSessionId')


# def get_default_project_id(server, auth_token, site_id):
    # """
    # Returns the project ID for the 'default' project on the Tableau server.

    # 'server'        specified server address
    # 'auth_token'    authentication token that grants user access to API calls
    # 'site_id'       ID of the site that the user is signed into
    # """
    # page_num, page_size = 1, 100   # Default paginating values

    # # Builds the request
    # url = server + "/api/{0}/sites/{1}/projects".format(VERSION, site_id)
    # paged_url = url + "?pageSize={0}&pageNumber={1}".format(page_size, page_num)
    # server_response = requests.get(paged_url, headers={'x-tableau-auth': auth_token})
    # _check_status(server_response, 200)
    # xml_response = ET.fromstring(_encode_for_display(server_response.text))

    # # Used to determine if more requests are required to find all projects on server
    # total_projects = int(xml_response.find('t:pagination', namespaces=xmlns).get('totalAvailable'))
    # max_page = int(math.ceil(total_projects / page_size))

    # projects = xml_response.findall('.//t:project', namespaces=xmlns)

    # Continue querying if more projects exist on the server
    # for page in range(2, max_page + 1):
        # paged_url = url + "?pageSize={0}&pageNumber={1}".format(page_size, page)
        # server_response = requests.get(paged_url, headers={'x-tableau-auth': auth_token})
        # _check_status(server_response, 200)
        # xml_response = ET.fromstring(_encode_for_display(server_response.text))
        # projects.extend(xml_response.findall('.//t:project', namespaces=xmlns))

    # Look through all projects to find the 'default' one
    # for project in projects:
        # if project.get('name') == 'default' or project.get('name') == 'Default':
            # return project.get('id')
    # raise LookupError("Project named 'default' was not found on server")
def get_workbook_id(server, auth_token, site_id, workbookname):
    wb_url = server + "/api/{0}/sites/{1}/workbooks".format(VERSION, site_id)
    server_response = requests.get(wb_url, headers={'x-tableau-auth': auth_token})
    _check_status(server_response, 200)
    xml_response = ET.fromstring(_encode_for_display(server_response.text))
    workbooks = xml_response.findall(".//{http://tableau.com/api}workbook")
    for workbook in workbooks:
        if workbook.get('name')==workbookname:
            workbookid = workbook.get('id')
    return workbookid

def download(server, auth_token, site_id, workbook_id):
    """
    Downloads the desired workbook from the server (temp-file).

    'server'        specified server address
    'auth_token'    authentication token that grants user access to API calls
    'site_id'       ID of the site that the user is signed into
    'workbook_id'   ID of the workbook to download
    Returns the filename of the workbook downloaded.
    """
    print("\tDownloading workbook to a temp file")
    url = server + "/api/{0}/sites/{1}/workbooks/{2}/content?includeExtract=False".format(VERSION, site_id, workbook_id)
    server_response = requests.get(url, headers={'x-tableau-auth': auth_token})
    _check_status(server_response, 200)

    # Header format: Content-Disposition: name="tableau_workbook"; filename="workbook-filename"
    filename = re.findall(r'filename="(.*)"', server_response.headers['Content-Disposition'])[0]
    with open(filename, 'wb') as f:
        f.write(server_response.content)
    return filename
	

def main():
    ##### STEP 0: INITIALIZATION #####
    if len(sys.argv) != 2:
        error = "1 argument needed (Workbookname)"
        raise UserDefinedFieldError(error)
    server = ''
    username = ''
    workbookname = sys.argv[1]
    password = ""


    # Prompt for a server - include the http://
    if server == "":
        server = raw_input("\nServer : ")

    # Prompt for a username
    if username == "":
        username = raw_input("\nUser name: ")

	# Prompt for password
    if password == "":
        password = getpass.getpass("Password: ")
	
    ##### STEP 1: SIGN IN #####
    print("\n1. Signing in as " + username)	
    auth_token, site_id = sign_in(server, username, password)
	
	### STEP 2: get workbook id
    workbook_id = get_workbook_id(server, auth_token, site_id,workbookname)
	
	#### STEP 3: downloading
    print("\tDownloading...")
    filename = download(server, auth_token, site_id, workbook_id)

	#### STEP 4: unzip workbook	
    zip = zipfile.ZipFile(filename)
    zip.extractall()
	
    ##### STEP 5: SIGN OUT #####
    print("\n4. Signing out, and invalidating the authentication token")
    sign_out(server, auth_token)
    auth_token = None


if __name__ == '__main__':
    main()
