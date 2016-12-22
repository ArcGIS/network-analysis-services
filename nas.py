########################################################################################
## Copyright 2016 Esri
## Licensed under the Apache License, Version 2.0 (the "License");
## you may not use this file except in compliance with the License.
## You may obtain a copy of the License at
## http://www.apache.org/licenses/LICENSE-2.0
## Unless required by applicable law or agreed to in writing, software
## distributed under the License is distributed on an "AS IS" BASIS,
## WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
## See the License for the specific language governing permissions and
## limitations under the License.
########################################################################################

'''A module implementing tools that are used to publish network analysis services.'''

import os
import logging
import sys
import locale
import ConfigParser
import traceback
import time
import fnmatch
import urllib
import urllib2
import gzip
import json
import io
import ssl 
try:
    import cStringIO as sio
except ImportError as ex:
    import StringIO as sio

try:
    import cPickle as pickle
except:
    import pickle

import arcpy
import hostedgp
import NAUtils as nau

##Module level variables
LOG_LEVEL = logging.INFO

def strip_quotes(value):
    '''Strips the single quote from the start and end of each string value.
    '''
    if isinstance(value, list):
        return [x.lstrip("'").rstrip("'") for x in value]
    elif isinstance(value, (str, unicode)):
        return value.lstrip("'").rstrip("'")
    else:
        return value

def make_http_request(url, query_params=None, content_coding_token="gzip", referer=None, headers=None,
                      ignore_ssl_errors=False):
    """Makes an HTTP request and returns the JSON response. content_coding_token must be 'gzip' or 'identity'.
    Specify a referer if the requests require it to be specified. headers is dict containing additional values
    that are passed in the request header
    """
 
    response_dict = {}
    if query_params == None:
        query_params = {}
    if not "f" in query_params:
        query_params["f"] = "json"
 
    request = urllib2.Request(url)
    request.add_data(urllib.urlencode(query_params))
    request.add_header("Accept-Encoding", content_coding_token)
    if referer:
        request.add_header("Referer", referer)
    if headers:
        for header in headers:
            request.add_header(header, headers[header])
    
    if ignore_ssl_errors:
        response = urllib2.urlopen(request, context=ssl._create_unverified_context())
    else:
        try:
            response = urllib2.urlopen(request)
        except urllib2.URLError as ex:
            #revert to default https validation that was used in python 2.7.8 and earlier
            ssl_context = ssl._create_unverified_context()
            response = urllib2.urlopen(request, context=ssl_context)         
    #If content_coding_token is identity, response does not need any transformation. If content_coding_token is
    #gzip, the response needs special handling before converting to JSON.
    if content_coding_token == "gzip":
        if response.info().get("Content-Encoding") == "gzip":
            buf = sio.StringIO(response.read())
            response = gzip.GzipFile(fileobj=buf)
    response_dict = json.load(response)
    return response_dict

def select_nds_extent_polygons(extentPolygons,extentPolygonFields,points):
    '''Select NDS based on polygons of network dataset extents. ExtentPolygons is assumed to be a feature layer.
    For remote NDS return the connection file and service name in addition to the name. points is a list of all
    the input feature classes that should be considered. The first element in the list should be the feature class
    whose first point determines the selection criteria. For example for Location-Allocation, the first
    demand point is first evaluated to see if it falls in more than one extent. If it does not fall in any extent,
    we return empty network dataset. If the first point falls in only one extent, return the network dataset.
    If first point falls in more than on extent, then combine all the inputs. If all inputs are in a single extent,
    use the network dataset. If all inputs are in two extents, use the network dataset with lower rank. 
    If all inputs are not within any extent fail with a message saying that all points are not in a single extent.'''
    
    outputNDS = ""
    connectionFile = ""
    serviceName = ""
    remoteConnectionInfo = None
    selectedRowCount = 0
    
    #Get a list of point shapes. Always project geometry to spatial reference of extent polygons
    sr = arcpy.Describe(extentPolygons).spatialReference
    #We assume that if the first demand point falls within the network dataset extent all 
    #all points from all inputs are within the same extent 
    with arcpy.da.SearchCursor(points[0], "SHAPE@", "", sr) as cursor:
        firstPoint = cursor.next()[0]    
    #We assume that extentPolygons is a feature layer
    #If output coordinate system is set, we need to use the coordinate system of extent polygons.
    origOutputSR = arcpy.env.outputCoordinateSystem
    arcpy.env.outputCoordinateSystem = sr
    layerWithSelection = arcpy.management.SelectLayerByLocation(extentPolygons, "COMPLETELY_CONTAINS",
                                                                firstPoint).getOutput(0)
    
    with arcpy.da.SearchCursor(layerWithSelection, extentPolygonFields) as cursor:
        for row in cursor:
            #For most cases, we should have only one selected row if the point falls into any polygon
            selectedRowCount += 1
            if selectedRowCount == 1:
                outputNDS = row[0]
                remoteConnectionInfo = row[1:3]
            else:
                #The first point falls in multiple polygons. Create a multipoint with all the inputs
                ptList = []
                for inputPoint in points:
                    with arcpy.da.SearchCursor(inputPoint, "SHAPE@", "", sr) as cursor:
                        ptList += [row[0].firstPoint for row in cursor]
                inputMultiPoint = arcpy.Multipoint(arcpy.Array(ptList), sr)
                #Check if multipoint is in at least one region. If yes select the region with highest rank
                #Otherwise return an error
                overlappingExtentsLayer = arcpy.management.SelectLayerByLocation(extentPolygons, "COMPLETELY_CONTAINS",
                                                                                 inputMultiPoint).getOutput(0)
                arcpy.management.Delete(inputMultiPoint)
                with arcpy.da.SearchCursor(overlappingExtentsLayer, extentPolygonFields) as cursor:
                    #sort by rank field (fourth field in the cursor)
                    sorted_cursor = sorted(cursor, key=lambda row: row[3])
                if len(sorted_cursor):
                    #pick the first row
                    first_row = sorted_cursor[0]
                    outputNDS = first_row[0]
                    remoteConnectionInfo = first_row[1:3]
                else:
                    arcpy.AddIDMessage("ERROR", 30140)
                    raise InputError 
                #break out of loop in case we have more than 2 polygons that contain input points
                break
    #Check if the selected NDS is remote
    if remoteConnectionInfo and remoteConnectionInfo[-1]:
        #Connection file is in same workspace as layer
        connection_file_name, serviceName = remoteConnectionInfo[-1].split(";", 1)
        connectionFile = os.path.join(os.path.dirname(layerWithSelection.workspacePath),
                                      connection_file_name)
        

    arcpy.management.SelectLayerByAttribute(extentPolygons, "CLEAR_SELECTION")
    arcpy.env.outputCoordinateSystem = origOutputSR
    
    #Fail if the points do not fall in any network datasets    
    if outputNDS == "":
        arcpy.AddIDMessage("ERROR", 30137)
        raise InputError          
    
    return (outputNDS, connectionFile, serviceName)

def add_remote_toolbox(connection_file, service):
    '''Adds a remote toolbox using the ags connection file and returns the remote tool name and the path to the toolbox.
    The remote tool name can be used with arcpy.gp to call the tool. The toolbox path can be used to remove the toolbox
    after execution of the remote tool'''

    #Get the service_name and task_name and task_alias from the service
    service_name, task_name = service.split(";")
    task_alias = service_name.split("/")[-1]
    #Add the remote toolbox
    tbx = "{0};{1}".format(connection_file, service_name)
    tbx_added = False
    try:
        arcpy.gp.addToolbox(tbx)
        remote_tool_name = u"{0}_{1}".format(task_name, task_alias)
        return remote_tool_name, tbx
    except Exception as ex:
        raise arcpy.ExecuteError

def execute_remote_tool(tbx, task_name, task_params):
    '''Executes a remote GP tool and returns the result object from the tool execution. Removes the remote toolbox
    after execution'''
    tool = getattr(arcpy.gp, task_name)
    result = tool(*task_params)
    while result.status < 4:
        time.sleep(1)
    #Remove the toolbox
    arcpy.gp.removeToolbox(tbx)
    return result

def get_valid_restrictions_remote_tool(remote_tool_restriction_param, input_restrictions):
    '''Returns a list of restriction attribute names that are valid for a remote tool. Outputs a warning message
    if some of the input restrictions are not valid for use with remote tool.
    remote_tool_restriction_param is the parameter object for the restriction parameter on the remote tool
    input_restrictions is a list of restrictions that will be passed to the remote tool. if all input restrictions are 
    valid, then input_restrictions is returned as is.'''

    remote_tool_nds_restrictions = remote_tool_restriction_param.filter.list
    remote_tool_nds_restrictions_set = set(remote_tool_nds_restrictions)
    input_restrictions_set = set(input_restrictions)
    remote_tool_unsupported_restrictions = list(input_restrictions_set.difference(remote_tool_nds_restrictions_set))
    if remote_tool_unsupported_restrictions:
        remote_tool_input_restrictions = list(input_restrictions_set.intersection(remote_tool_nds_restrictions_set))
        #add warning message for ignoring un-supported restrictions
        arcpy.AddIDMessage("WARNING", 30113, ", ".join(remote_tool_unsupported_restrictions))
        return remote_tool_input_restrictions
    else:
        return input_restrictions

def get_rest_info():
    '''Return a dictionary containing rest/info response when running in ArcGIS Server context. Returns an empty
    dictionary otherwise'''

    rest_info = {}
    running_on_server = arcpy.GetInstallInfo().get('ProductName', "").lower() == 'server'
    if running_on_server:
        try:
            rest_info = make_http_request("http://localhost:6080/arcgis/rest/info")
        except Exception as ex:
            #try with https in case the server is configured as https only.
            try:
                rest_info = make_http_request("https://localhost:6443/arcgis/rest/info", ignore_ssl_errors=True)
            except Exception as ex:
                rest_info = {}
    return rest_info

def init_hostedgp():
    '''Return an instance of hostedgp'''

    try:
        #Do not perform a tenant check as we might run this from a federated server that is not acting as a hosted
        #server (e.g AGOL servers). We are not using hostedgp to create hosted feature services. So tenant check is
        #not required.
        hgp = hostedgp.HostedGP(tenantCheck=False)
        return hgp
    except Exception as ex:
        if LOG_LEVEL == logging.DEBUG:
            arcpy.AddMessage("An error occured when using hostedgp")
            arcpy.AddMessage("error function: {}, error message: {}".format(ex.func, ex.errmsg))
        return None

def get_portal_self(hgp=None):
    '''Return a dictionary containing self response from a portal that the server federates to. Returns an empty
    dictionary if not running on server or running on a non-federated server'''

    portal_self = {}
    try:
        if not hgp:
            hgp = init_hostedgp()
        portal_self = json.loads(hgp.GetSelf())
    except Exception as ex:
        if LOG_LEVEL == logging.DEBUG:
            arcpy.AddMessage("An error occured when using hostedgp")
            arcpy.AddMessage("error function: {}, error message: {}".format(ex.func, ex.errmsg))
        portal_self = {}
    return portal_self

def str_to_float(input_str):
    '''converts a string to a float'''

    #set the locale for all categories to the users default setting. This is required on some OS like German
    #and Russian to read the appropriate decimal separator 

    locale.setlocale(locale.LC_ALL, '')
    try:
        return locale.atof(input_str)
    except UnicodeDecodeError:
        return locale.atof(input_str.encode("utf-8", "ignore"))
    except:
        if isinstance(input_str, (unicode, str)):
            if "," in input_str:
                input_str = input_str.replace(",", ".")
                return float(input_str)
            else:
                raise
        else:
            raise

class Logger(object):
    '''Log GP messages. If a log file is provided, log messages to the file.'''

    def __init__(self, log_level=logging.INFO, log_file=None):
        self.logLevel = log_level
        self.DEBUG = True if self.logLevel == logging.DEBUG else False
        self.fileLogger = None
        self.logFile = log_file
        #If a log file is provided, log all messages irrespective of the log level to the log file
        if self.logFile:
            self.fileLogger = logging.getLogger("GPMessageFileLogger")
            self.fileLogger.setLevel(logging.DEBUG)
            if not self.fileLogger.handlers:
                fh = logging.FileHandler(self.logFile, "w", "utf-8")
                fh_formatter = logging.Formatter('%(levelname)s | %(asctime)s | %(name)s | %(module)s | %(funcName)s | %(lineno)d | %(message)s',
                                                 '%Y-%m-%d %H:%M:%S')
                fh.setFormatter(fh_formatter)
                self.fileLogger.addHandler(fh)
                

    def debug(self, msg):
        '''Write a info GP message only if log level is DEBUG'''
        if msg:
            if self.logLevel == logging.DEBUG:
                arcpy.AddMessage(msg)
            if self.fileLogger:
                self.fileLogger.debug(msg)


    def info(self, msg):
        '''Write a info GP message'''
        if msg:
            arcpy.AddMessage(msg)
            if self.fileLogger:
                self.fileLogger.info(msg)

    def error(self, msg):
        '''Write a GP error message'''
        if msg:
            arcpy.AddError(msg)
            if self.fileLogger:
                self.fileLogger.error(msg)

    def warning(self, msg):
        '''Write a GP warning message'''
        if msg:
            arcpy.AddWarning(msg)
            if self.fileLogger:
                self.fileLogger.warn(msg)

    def exception(self, msg):
        '''Write the full traceback information as GP error message'''
        if msg:
            arcpy.AddError(msg)
            if self.DEBUG:
                for err_msg in traceback.format_exception(*sys.exc_info()):
                    arcpy.AddError(err_msg)
            if self.fileLogger:
                self.fileLogger.exception(msg)

class InputError(Exception):
    '''Raise this expection whenever a throtlling condition is not met'''
    pass

class NetworkAnalysisTool(object):
    '''base class for all network analysis tool that provides the user interface.'''

    MEASUREMENT_UNITS = ["Meters", "Kilometers", "Feet", "Yards", "Miles", "Nautical Miles",
                         "Seconds", "Minutes", "Hours", "Days"]
    TIME_UNITS = ["Seconds", "Minutes", "Hours", "Days"]
    DISTANCE_UNITS = ["Meters", "Kilometers", "Feet", "Yards", "Miles", "NauticalMiles"]
    TIME_ZONE_USAGE = ["Geographically Local", "UTC"]
    NETWORK_DATASET_PROPERTIES_FILENAME = "NetworkDatasetProperties.ini"
    TOOL_INFO_FILENAME = "ToolInfo.json"

    def __init__(self):
        '''Base class constructor'''

        #Need to skip validation when running as a GP service
        self.runningOnServer = arcpy.GetInstallInfo().get('ProductName', "").lower() == 'server'

        #Names used in multiple instance methods
        self.layerFilesFolder = os.path.join(os.path.dirname(__file__), "data")
        
        #TODO: MAke this as static class attribute
        self.attributeParameterFields = ("AttributeName", "ParameterName", "ParameterValue")
        self.parser = ConfigParser.SafeConfigParser()

        #Store frequently used tool parameter indices as instance attributes. These must be overwritten in the derived
        #class 
        self.SUPPORTING_FILES_FOLDER_PARAM_INDEX = None
        self.NETWORK_DATASETS_PARAM_INDEX = None
        self.NETWORK_DATASET_EXTENTS_PARAM_INDEX = None
        self.ANALYSIS_REGION_PARAM_INDEX = None
        self.UTURN_POLICY_PARAM_INDEX = None
        self.HIERARCHY_PARAM_INDEX = None
        self.RESTRICTIONS_PARAM_INDEX = None
        self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX = None
        self.SIMPLIFICATION_TOL_PARAM_INDEX = None

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""

        if self.runningOnServer:
            return
        
        #Set the defaults for tool parameters based on the network datasets
        self._updateNDSBasedParamDefaults(parameters)
        
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""

        if self.runningOnServer:
            return

        network_datasets_param = parameters[self.NETWORK_DATASETS_PARAM_INDEX]

        #Network Datasets should be specified using a network dataset layers
        self._requireNetworkDatasetLayers(network_datasets_param)

        #Network Dataset Properties file must exist in the Supporting Files folder.
        self._requireNetworkDatasetPropertiesFile(parameters[self.SUPPORTING_FILES_FOLDER_PARAM_INDEX])

        #Network dataset extents parameter is required for mutiple network datasets
        self._requireNetworkDatasetExtents(network_datasets_param, parameters[self.NETWORK_DATASET_EXTENTS_PARAM_INDEX])

        return

    def _updateAnalysisRegionValueList(self, analysis_region_param, network_datasets_param_value,
                                       nds_extents_param):
        '''Populate the analysis region value list based on the network dataset layer names
        '''

        if network_datasets_param_value:
            analysis_region_param.filter.list = network_datasets_param_value
            #Add the values from RegionName field in the network dataset extents feature layer that are not already
            #included as network dataset layer names. This will be the case for remote services like Korea.
            nds_extents_param_value = nds_extents_param.valueAsText
            if nds_extents_param_value:
                nds_extents_param_value = nds_extents_param_value.split(";")[0]
                nds_extents_param_value = strip_quotes(nds_extents_param_value)
                remote_regions = []
                with arcpy.da.SearchCursor(nds_extents_param_value, NetworkAnalysisService.EXTENT_FIELDS[0]) as cursor:
                    for row in cursor:
                        if not row[0] in network_datasets_param_value:
                            remote_regions.append(row[0])
                analysis_region_param.filter.list += remote_regions
        else:
            analysis_region_param.filter.list = []

    def _updateNDSBasedParamDefaults(self, parameters):
        '''Update the default values for tool parameters based on the network dataset'''

        self.networkDatasetsParam = parameters[self.NETWORK_DATASETS_PARAM_INDEX]
        self.supportingFilesFolderParam = parameters[self.SUPPORTING_FILES_FOLDER_PARAM_INDEX]
        self.uTurnPolicyParam = parameters[self.UTURN_POLICY_PARAM_INDEX]
        self.hierarchyParam = parameters[self.HIERARCHY_PARAM_INDEX]
        self.restrictionsParam = parameters[self.RESTRICTIONS_PARAM_INDEX]
        self.attributeParametersParam = parameters[self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX]
        if self.SIMPLIFICATION_TOL_PARAM_INDEX == -1:
            self.simplificationToleranceParam = None
        else:
            self.simplificationToleranceParam = parameters[self.SIMPLIFICATION_TOL_PARAM_INDEX]

        #Read the network dataset properties from config file
        config_file_exists = False
        supporting_files_folder_param_value = self.supportingFilesFolderParam.valueAsText
        if supporting_files_folder_param_value:
            config_file = os.path.join(supporting_files_folder_param_value, self.NETWORK_DATASET_PROPERTIES_FILENAME)
            if os.path.exists(config_file):
                config_file_exists = True
                self.parser.read(config_file)
                #Set the network datasets param value based on all the section names
                if not self.networkDatasetsParam.valueAsText and not self.networkDatasetsParam.altered:
                    self.networkDatasetsParam.values = [[section] for section in self.parser.sections()]

        #Remove any single quotes from network dataset names
        network_datasets_param_value = self.networkDatasetsParam.valueAsText
        if network_datasets_param_value:
            network_datasets_param_value = strip_quotes(network_datasets_param_value.split(";"))

        #Set the analysis region parameter value list based on network dataset names
        self._updateAnalysisRegionValueList(parameters[self.ANALYSIS_REGION_PARAM_INDEX], network_datasets_param_value,
                                            parameters[self.NETWORK_DATASET_EXTENTS_PARAM_INDEX])
        
        #Set the defaults for tool parameters based on the network datasets
        if network_datasets_param_value and config_file_exists:
            if self.networkDatasetsParam.hasBeenValidated == False or self.supportingFilesFolderParam.hasBeenValidated == False:
                try:
                    self._getNetworkProps(network_datasets_param_value)
                except:
                    self._resetNetworkProps()
                    return
                    #raise
        else:
            self._resetNetworkProps()

    def _requireNetworkDatasetExtents(self, network_datasets_param, network_dataset_extents_param):
        '''Raise a parameter validation error if network dataset extents in not specified when dealing with multiple
        network datasets'''
        
        network_datasets = network_datasets_param.valueAsText
        network_dataset_extents = network_dataset_extents_param.valueAsText

        if network_datasets and len(network_datasets.split(";")) > 1:
            if not network_dataset_extents:
                #Raise Error 735: %s: Value is required
                network_dataset_extents_param.setIDMessage("ERROR", 735, network_dataset_extents_param.displayName)

    def _requireNetworkDatasetLayers(self, network_datasets_param):
        '''Raise a parameter validation error if network datasets are specified using catalog paths'''

        network_datasets = network_datasets_param.valueAsText
        if network_datasets:
            for network_dataset in strip_quotes(network_datasets.split(";")):
                desc = arcpy.Describe(network_dataset)
                #time.sleep(30)
                if desc.dataType == "NetworkDataset":
                    msg = "The network dataset {0} is referenced with a catalog path instead of a network dataset layer"
                    network_datasets_param.setErrorMessage(msg.format(desc.baseName))

    def _requireNetworkDatasetPropertiesFile(self, supporting_files_folder_param):
        '''Raise an error if the network dataset properties file does not exist in the supporting files folder'''

        supporting_files_folder = supporting_files_folder_param.valueAsText
        if supporting_files_folder:
            properties_file = os.path.join(supporting_files_folder, self.NETWORK_DATASET_PROPERTIES_FILENAME)
            if not os.path.exists(properties_file):
                msg = u"Network dataset properties file, {0}, does not exist in {1} folder."
                supporting_files_folder_param.setErrorMessage(msg.format(self.NETWORK_DATASET_PROPERTIES_FILENAME,
                                                                         supporting_files_folder))

    def _resetNetworkProps(self):
        """Resets the network dataset derived parameters to nothing"""

        self.restrictionsParam.filter.list = []
        self.restrictionsParam.value = ""
        self._resetAttributeParametersTable()

    def _resetAttributeParametersTable(self):
        '''Deletes all rows from the attribute parameter record set.'''
        
        param_value = self.attributeParametersParam.value
        if param_value:    
            with arcpy.da.UpdateCursor(param_value, "*") as cursor:
                for row in cursor:        
                    cursor.deleteRow()

    def _setAttributeParameterValues(self, attribute_parameters):
        '''Sets the value for the attribute parameters parameter.'''
        #Clear any existing rows    
        self._resetAttributeParametersTable()
        with arcpy.da.InsertCursor(self.attributeParametersParam.value, self.attributeParameterFields) as rows:
            if isinstance(attribute_parameters, dict): 
                values = sorted(attribute_parameters.values())
            else:
                values = sorted(attribute_parameters)
            for val in values:
                rows.insertRow(val)

    def _setTravelModeSettings(self, str_travel_mode):
        '''Sets the default values for network dataset dependent parameters in the custom travel mode category based
        on a travel mode value.'''
        
        uturn_keywords = {
            "esriNFSBAllowBacktrack" : "Allowed",
            "esriNFSBNoBacktrack" : "Not Allowed",
            "esriNFSBAtDeadEndsOnly" : "Allowed Only at Dead Ends",
            "esriNFSBAtDeadEndsAndIntersections" : "Allowed Only at Intersections and Dead Ends"
        }

        esri_units = {
            "UnkownUnits": "Unknown",
            "DecimalDegrees" : "Decimal degrees",
            "NauticalMiles" : "Nautical Miles",
        }
        
        restriction_usage_values = {
            "-1.0": "PROHIBITED",
            "5.0": "AVOID_HIGH",
            "2.0": "AVOID_MEDIUM",
            "1.3": "AVOID_LOW",
            "0.5" : "PREFER_MEDIUM",
            "0.8" : "PREFER_LOW",
            "0.2" : "PREFER_HIGH"
        }		

        travel_mode_settings = json.loads(str_travel_mode)
        uturn_param_value = uturn_keywords.get(travel_mode_settings.get("uturnAtJunctions"))
        if not uturn_param_value in self.uTurnPolicyParam.filter.list:
            uturn_param_value = NetworkAnalysisService.UTURN_KEYWORDS.get(uturn_param_value, "")
        self.uTurnPolicyParam.value = uturn_param_value
        #Do not use hierarchy for GenerateServiceAreas tool as we should be using  service area index.
        hierarchy_param_value = travel_mode_settings.get("useHierarchy")
        if self.__class__.__name__ == "GenerateServiceAreas":
            hierarchy_param_value = False
        self.hierarchyParam.value = hierarchy_param_value

        tolerance_units = travel_mode_settings.get("simplificationToleranceUnits").lstrip("esri")
        tolerance_units = esri_units.get(tolerance_units, tolerance_units)
        if self.simplificationToleranceParam:
            self.simplificationToleranceParam.value = u"{0} {1}".format(travel_mode_settings.get("simplificationTolerance"),
                                                                        tolerance_units)
        self.restrictionsParam.value = travel_mode_settings.get("restrictionAttributeNames")
        attribute_parameters = travel_mode_settings.get("attributeParameterValues")
        if attribute_parameters:
            travel_mode_attr_param_values = {}
            for attribute_parameter in attribute_parameters:
                attr_name = attribute_parameter["attributeName"]
                param_name = attribute_parameter["parameterName"]
                param_value = attribute_parameter["value"]
                #Convert restriction usage parameter values to string keywords
                if param_name.upper() == "RESTRICTION USAGE":
                    #try to convert the parameter value to a float and then to unicode
                    try:
                        param_value = float(param_value)
                        param_value = unicode(param_value)
                        param_value = restriction_usage_values.get(param_value, param_value)
                    except Exception as ex:
                        pass
                travel_mode_attr_param_values[(attr_name, param_name)] = param_value
            with arcpy.da.UpdateCursor(self.attributeParametersParam.value, self.attributeParameterFields) as cursor:
                for row in cursor:
                    key = (row[0], row[1])
                    if key in travel_mode_attr_param_values:
                        row[2] = travel_mode_attr_param_values[key]
                    cursor.updateRow(row)
        return

    def _getNetworkProps(self, networks):
        '''Determine the restrictions and attribute parameter values for all network datasets.'''

        #Assume that the first network dataset is the template network dataset
        template_nds = networks[0]

        #Read template network dataset properties from the properties file
        all_restrictions = self.parser.get(template_nds, "restrictions").split(";")
        all_default_restrictions = self.parser.get(template_nds, "default_restrictions").split(";")
        all_attr_params = self.parser.get(template_nds, "attribute_parameter_values")
        all_attr_params = pickle.loads(all_attr_params)
        all_travel_modes = pickle.loads(self.parser.get(template_nds, "travel_modes"))
        if all_travel_modes:
            all_travel_modes = list({k[0] for k in all_travel_modes})
        else:
            all_travel_modes = []

        #Set the lists for Restriction   
        self.restrictionsParam.filter.list = sorted(all_restrictions)
        #Set the default restrictions
        if not self.restrictionsParam.altered:
            self.restrictionsParam.value = ";".join(all_default_restrictions)

        #Update the attribute parameters.     
        #if not self.attributeParametersParam.altered:
        #if True:
        if all_attr_params:
            self._setAttributeParameterValues(all_attr_params)

        #Update tool parameters in custom travel mode category with values from default custom travel mode for
        #template network dataset layer
        self._setTravelModeSettings(self.parser.get(template_nds, "default_custom_travel_mode"))

        return

    def _initializeCommonParameters(self):
        '''Create parameters common to all network analysis tool'''

        parameters = []
        
        #Network Datasets parameter
        nds_param = arcpy.Parameter("Network_Datasets", "Network Datasets", "Input", "GPValueTable", "Required")
        nds_param.columns = [["GPNetworkDatasetLayer", "Network Dataset"]]
        parameters.append(nds_param)

        #Supporting Files Folder parameter
        parameters.append(arcpy.Parameter("Supporting_Files_Folder", "Supporting Files Folder", "Input", "DEFolder",
                                          "Required"))
        
        #Network Dataset Extents parameters
        nds_extents_param = arcpy.Parameter("Network_Dataset_Extents", "Network Dataset Extents", "Input",
                                            "GPValueTable", "Optional")
        nds_extents_param.columns = [["GPFeatureLayer", "Network Dataset Extents Layer"]]
        parameters.append(nds_extents_param)

        #Analysis Region parameter
        analysis_region_param = arcpy.Parameter("Analysis_Region", "Analysis Region", "Input", "GPString", "Optional")
        analysis_region_param.filter.list = []
        analysis_region_param.category = "Advanced Analysis"
        parameters.append(analysis_region_param)

        #Time of day parameter
        time_of_day_param = arcpy.Parameter("Time_of_Day", "Time of Day", "Input", "GPDate", "Optional")
        time_of_day_param.category = "Advanced Analysis" 
        parameters.append(time_of_day_param)

        #Time zone for time of day parameter
        time_zone_param = arcpy.Parameter("Time_Zone_for_Time_of_Day", "Time Zone for Time of Day", "Input",
                                              "GPString", "Optional")
        time_zone_param.category = "Advanced Analysis"
        time_zone_param.filter.list = self.TIME_ZONE_USAGE
        time_zone_param.value = "Geographically Local"
        parameters.append(time_zone_param)
        
        #U-turn at junctions parameter
        uturn_param = arcpy.Parameter("UTurn_at_Junctions", "UTurn at Junctions", "Input", "GPString", "Optional")
        uturn_param.category = "Custom Travel Mode"
        uturn_param.filter.list = ["Allowed", "Not Allowed", "Allowed Only at Dead Ends",
                                   "Allowed Only at Intersections and Dead Ends"]
        uturn_param.value = "Allowed"
        parameters.append(uturn_param) 

        #Point barriers parameter
        point_barriers_param = arcpy.Parameter("Point_Barriers", "Point Barriers", "Input", "GPFeatureRecordSetLayer",
                                               "Optional")
        point_barriers_param.category = "Barriers"
        point_barriers_param.value = os.path.join(self.layerFilesFolder,  "PointBarriers1.lyr")
        parameters.append(point_barriers_param)

        #Line barriers parameter
        line_barriers_param = arcpy.Parameter("Line_Barriers", "Line Barriers", "Input", "GPFeatureRecordSetLayer",
                                              "Optional")
        line_barriers_param.category = "Barriers"
        line_barriers_param.value = os.path.join(self.layerFilesFolder, "LineBarriers.lyr")
        parameters.append(line_barriers_param)

        #Polygon barriers parameter
        polygon_barriers_param = arcpy.Parameter("Polygon_Barriers", "Polygon Barriers", "Input",
                                                 "GPFeatureRecordSetLayer", "Optional")
        polygon_barriers_param.category = "Barriers"
        polygon_barriers_param.value = os.path.join(self.layerFilesFolder, "PolygonBarriers1.lyr")
        parameters.append(polygon_barriers_param)
        
        #Use hierarchy parameter
        use_hierarchy_param = arcpy.Parameter("Use_Hierarchy", "Use Hierarchy", "Input", "GPBoolean", "Optional")
        use_hierarchy_param.category = "Custom Travel Mode"
        use_hierarchy_param.filter.list = ["USE_HIERARCHY", "NO_HIERARCHY"]
        use_hierarchy_param.value = "USE_HIERARCHY"
        parameters.append(use_hierarchy_param)
        
        #Restrictions parameter
        restrictions_param = arcpy.Parameter("Restrictions", "Restrictions", "Input", "GPString", "Optional",
                                             multiValue=True)
        restrictions_param.category = "Custom Travel Mode"
        parameters.append(restrictions_param)
        
        #Attribute parameter values parameter
        attribute_parameter_values_param = arcpy.Parameter("Attribute_Parameter_Values", "Attribute Parameter Values",
                                                           "Input", "GPRecordSet", "Optional")
        attribute_parameter_values_param.category = "Custom Travel Mode"
        attribute_parameter_values_param.value = os.path.join(self.layerFilesFolder, "schema.gdb",
                                                              "AttributeParameterValues")
        parameters.append(attribute_parameter_values_param)

        #Route line simplification tolerance parameter
        simplification_tolerance_param = arcpy.Parameter("Route_Line_Simplification_Tolerance",
                                                         "Route Line Simplification Tolerance", "Input",
                                                         "GPLinearUnit", "Optional")
        simplification_tolerance_param.category = "Custom Travel Mode"
        simplification_tolerance_param.value = "10 Meters"
        parameters.append(simplification_tolerance_param)
        
        #Impedance parameter
        impedance_param = arcpy.Parameter("Impedance", "Impedance", "Input", "GPString", "Optional")
        impedance_param.category = "Custom Travel Mode"
        impedance_param.filter.list = ["Drive Time", "Truck Time", "Walk Time", "Travel Distance"]
        impedance_param.value = "Drive Time"
        parameters.append(impedance_param)
        
        #Travel mode parameter
        travel_mode_param = arcpy.Parameter("Travel_Mode", "Travel Mode", "Input", "GPString", "Optional")
        travel_mode_param.value = "Custom"
        parameters.append(travel_mode_param)

        #Save Output Network Analysis Layer parameter
        save_output_layer_param = arcpy.Parameter("Save_Output_Network_Analysis_Layer",
                                                  "Save Output Network Analysis Layer", "Input", "GPBoolean",
                                                  "Optional")
        save_output_layer_param.category = "Output"
        save_output_layer_param.filter.list = ["SAVE_OUTPUT_LAYER ", "NO_SAVE_OUTPUT_LAYER "]
        save_output_layer_param.value = False
        parameters.append(save_output_layer_param)

        #Overrides parameter
        overrides_param = arcpy.Parameter("Overrides", "Overrides", "Input", "GPString", "Optional")
        overrides_param.category = "Advanced Analysis"
        parameters.append(overrides_param)

        #Solve succeeded param
        solve_succeeded_param = arcpy.Parameter("Solve_Succeeded", "Solve Succeeded", "Output", "GPBoolean", "Derived")
        solve_succeeded_param.value = False 
        parameters.append(solve_succeeded_param)
        
        #Output Network Analysis Layer parameter
        output_layer_param = arcpy.Parameter("Output_Network_Analysis_Layer", "Output Network Analysis Layer",
                                             "Output", "DEFile", "Derived")
        parameters.append(output_layer_param) 

        return {param.name : param for param in parameters}

    def _initializeDirectionsParameters(self):
        '''Create directions releated parameters used by some network analysis tools.'''

        parameters = []

        #Populate directions parameter
        populate_directions_param = arcpy.Parameter("Populate_Directions", "Populate Directions", "Input",
                                                    "GPBoolean", "Optional")
        populate_directions_param.category = "Output"
        populate_directions_param.filter.list = ["DIRECTIONS", "NO_DIRECTIONS"]
        populate_directions_param.value = "NO_DIRECTIONS"
        parameters.append(populate_directions_param)

        #Directions language parameter
        directions_language_param = arcpy.Parameter("Directions_Language", "Directions Language", "Input", "GPString",
                                                    "Optional")
        directions_language_param.category = "Output"
        directions_language_param.value = "en"
        parameters.append(directions_language_param)

        #Directions distance units parameter
        directions_units_param = arcpy.Parameter("Directions_Distance_Units", "Directions Distance Units", "Input",
                                                 "GPString", "Optional")
        directions_units_param.category = "Output"
        directions_units_param.filter.list = ["Miles", "Kilometers", "Meters", "Feet", "Yards", "NauticalMiles"]
        directions_units_param.value = "Miles"
        parameters.append(directions_units_param)

        #Directions style name parameter
        directions_style_param = arcpy.Parameter("Directions_Style_Name", "Directions Style Name", "Input", "GPString",
                                                 "Optional")
        directions_style_param.category = "Output"
        directions_style_param.filter.list = ["NA Desktop", "NA Navigation"]
        directions_style_param.value = "NA Desktop"
        parameters.append(directions_style_param)

        #Save route data parameter
        save_route_data_param = arcpy.Parameter("Save_Route_Data", "Save Route Data", "Input", "GPBoolean", "Optional")
        save_route_data_param.category = "Output"
        save_route_data_param.filter.list = ["SAVE_ROUTE_DATA", "NO_SAVE_ROUTE_DATA"]
        save_route_data_param.value = "NO_SAVE_ROUTE_DATA"
        parameters.append(save_route_data_param)

        #Output route data parameter
        output_route_data_param = arcpy.Parameter("Output_Route_Data", "Output Route Data", "Output", "DEFile",
                                                  "Derived")
        parameters.append(output_route_data_param)

        return {param.name : param for param in parameters}

class NetworkAnalysisService(object):
    '''Base class for network analysis service which performs the core execution'''

    UTURN_KEYWORDS = {
        "Allowed" : "ALLOW_UTURNS",
        "Not Allowed" : "NO_UTURNS",
        "Allowed Only at Dead Ends" : "ALLOW_DEAD_ENDS_ONLY",
        "Allowed Only at Intersections and Dead Ends" : "ALLOW_DEAD_ENDS_AND_INTERSECTIONS_ONLY",
    }

    TIME_ZONE_USAGE_KEYWORDS = {
        "UTC" : "UTC",
        "Geographically Local" : "GEO_LOCAL"
    }

    ROUTE_SHAPE_KEYWORDS = {
        "True Shape" : "TRUE_LINES_WITHOUT_MEASURES",
        "True Shape with Measures" : "TRUE_LINES_WITH_MEASURES",
        "Straight Line" : "STRAIGHT_LINES",
        "None" : "NO_LINES"
    }
    
    TIME_UNITS = ('minutes','hours','days', 'seconds')

    ATTRIBUTE_PARAMETER_FIELDS = (u'AttributeName', u'ParameterName', u'ParameterValue')

    NDS_PROPERTY_NAMES = ("Time_Attribute", "Time_Attribute_Units",  "Distance_Attribute", "Distance_Attribute_Units",
                          "Feature_Locator_WHERE_Clause")
    METER_TO_MILES = 0.000621
    MAX_WALKING_MODE_DISTANCE_MILES = 50
    #Base classes should copy this list and provide correct value for thrid element
    EXTENT_FIELDS = ["RegionName", "RemoteConnection", "GPService", "Rank"]

    VRP_SERVICE_CAPABILITIES_KEYWORDS = {
        "maximumFeaturesAffectedByPointBarriers": "MAXIMUM POINT BARRIERS", 
        "maximumFeaturesAffectedByLineBarriers": "MAXIMUM FEATURES INTERSECTING LINE BARRIERS",
        "maximumFeaturesAffectedByPolygonBarriers": "MAXIMUM FEATURES INTERSECTING POLYGON BARRIERS",
        "maximumOrders": "MAXIMUM ORDERS",
        "maximumRoutes": "MAXIMUM ROUTES",
        "forceHierarchyBeyondDistance": "FORCE HIERARCHY BEYOND DISTANCE",
        "maximumOrdersPerRoute": "MAXIMUM ORDERS PER ROUTE"
    }

    SERVICE_CAPABILITIES_KEYWORDS = {
        "maximumFeaturesAffectedByPointBarriers": "Maximum_Features_Affected_by_Point_Barriers", 
        "maximumFeaturesAffectedByLineBarriers": "Maximum_Features_Affected_by_Line_Barriers",
        "maximumFeaturesAffectedByPolygonBarriers": "Maximum_Features_Affected_by_Polygon_Barriers",
        "forceHierarchyBeyondDistance": "Force_Hierarchy_Beyond_Distance",
        "maximumStops": "Maximum_Stops", 
        "maximumStopsPerRoute": "Maximum_Stops_per_Route",
        "maximumFacilities": "Maximum_Facilities", 
        "maximumFacilitiesToFind": "Maximum_Facilities_to_Find",
        "maximumIncidents": "Maximum_Incidents",
        "maximumOrigins" : "Maximum_Origins",
        "maximumDestinations" : "Maximum_Destinations",
        "maximumDemandPoints": "Maximum_Demand_Points",
        "maximumNumberOfBreaks": "Maximum_Number_of_Breaks",
        "maximumBreakTimeValue": "Maximum_Break_Time_Value",
        "maximumBreakDistanceValue": "Maximum_Break_Distance_Value",
        "forceHierarchyBeyondBreakTimeValue": "Force_Hierarchy_beyond_Break_Time_Value",
        "forceHierarchyBeyondBreakDistanceValue": "Force_Hierarchy_beyond_Break_Distance_Value",

    }

    SERVICE_NAMES = {
        "asyncClosestFacility": ["FindClosestFacilities"],
        "asyncLocationAllocation": ["SolveLocationAllocation"],
        "asyncRoute": ["FindRoutes"],
        "asyncServiceArea": ["GenerateServiceAreas"],
        "asyncVRP": ["SolveVehicleRoutingProblem"],
        "syncVRP": ["EditVehicleRoutingProblem"],
        "asyncODCostMatrix" : ["GenerateOriginDestinationCostMatrix"],
    }


    def __init__(self, *args, **kwargs):
        '''constructor'''

        #names used by the instance
        self.logger = Logger(LOG_LEVEL)

        #Store parameters common to all services as instance attributes

        self.networkDatasets = kwargs.get("Network_Datasets", None)
        if self.networkDatasets:
            self.networkDatasets = strip_quotes(self.networkDatasets.split(";"))
        
        self.networkDatasetPropertiesFile = kwargs.get("NDS_Properties_File", None)
        
        self.networkDatasetExtents = kwargs.get("Network_Dataset_Extents", None)
        if self.networkDatasetExtents:
            self.networkDatasetExtents = strip_quotes(self.networkDatasetExtents.split(";"))
            self.networkDatasetExtents = self.networkDatasetExtents[0]

        self.measurementUnits = kwargs.get("Measurement_Units", None)
        self.analysisRegion = kwargs.get("Analysis_Region", None)
        self.timeOfDay = kwargs.get("Time_of_Day", None)
        self.timeZoneUsage = kwargs.get("Time_Zone_for_Time_of_Day", None)
        self.useHierarchy = kwargs.get("Use_Hierarchy", None)
        self.uTurnAtJunctions = kwargs.get("Uturn_at_Junctions", None)
        self.pointBarriers = kwargs.get("Point_Barriers", None)
        self.lineBarriers = kwargs.get("Line_Barriers", None)
        self.polygonBarriers = kwargs.get("Polygon_Barriers", None)
        self.restrictions = kwargs.get("Restrictions", None)
        self.attributeParameterValues = kwargs.get("Attribute_Parameter_Values", None)
        self.travelMode = kwargs.get("Travel_Mode", None)
        self.impedance = kwargs.get("Impedance", None)
        self.saveLayerFile = kwargs.get("Save_Output_Network_Analysis_Layer", None)
        self.overrides = kwargs.get("Overrides", None)
        self.serviceCapabilities = kwargs.get("Service_Capabilities", None)

        #Derived outputs
        self.outputGeodatabase = kwargs.get("Output_Geodatabase", "in_memory")
        self.solveSucceeded = False
        self.outputLayer = ""

        #Other instance attributes
        self.toolResult = None
        self.isCustomTravelMode = True if self.travelMode and self.travelMode.upper() == "CUSTOM" else False
        #Assume measurement units are time based for tools such as solve VRP that do not support measurement units
        self.isMeasurementUnitsTimeBased = True
        if self.measurementUnits and not self.measurementUnits.lower() in self.TIME_UNITS:
            self.isMeasurementUnitsTimeBased = False
        self.supportedTravelModeNames = None

        #Read the tool info from the tool info json file
        with io.open(self.serviceCapabilities, "r", encoding="utf-8") as fp:
            self.toolInfoJSON = json.loads(fp.read(), "utf-8")
        self.templateNDSDescription = self.toolInfoJSON["networkDataset"]

        #Get the maximum records set for the service
        service_properties = json.loads(arcpy.gp._arc_object.serviceproperties())
        self.maxFeatures = 1000
        if "maximumRecords" in service_properties:
            self.maxFeatures = int(service_properties["maximumRecords"])
        
    def _checkNetworkDatasetExtents(self):
        '''If we have more than one network datasets, then network dataset extents is requried'''

        if len(self.networkDatasets) > 1:
            if self.networkDatasetExtents:
                self.networkDatasetExtents = self.networkDatasetExtents[0].lstrip("'").rstrip("'")
                self.logger.debug("Reading network dataset extents from {0}".format(extents))
                #TODO: Check if the extents feature class has the expected schema.
            else:
                arcpy.AddIDMessage("ERROR", 735, "Network Dataset Extents")
                raise arcpy.ExecuteError

    def _getServiceCapabilities(self):
        '''Convert service capabilities into a dictionary of tool parameters that can be passed to big button tool'''

        infinity = sys.maxint
        tool_name = self.__class__.__name__
       
        def convert_units(value_limit_name, unit_limit_name, nds_attribute_units):
            '''Convert the limits in distance or time attribute units supported by the network dataset'''
            value_units = ""
            if unit_limit_name in service_limits:
                value_units = service_limits.pop(unit_limit_name)
            value = service_limits.get(value_limit_name, None)

            if value and value_units:
                if value_units.lower() != nds_attribute_units.lower():
                    value = nau.convert_units(value, value_units, nds_attribute_units)
                    service_limits[value_limit_name] = str_to_float(value)
        
        service_limits = self.toolInfoJSON["serviceLimits"][self.HELPER_SERVICES_KEY][tool_name]
        
        #Determine the distance and time attribute units
        if self.isCustomTravelMode:
            distance_attribute_units = self.parser.get(self.templateNDS, "distance_attribute_units")
            time_attribute_units = self.parser.get(self.templateNDS, "time_attribute_units")
        else:
            #Get units based on time and distance attribute from the travel mode
            nds_cost_attribute_units = {attr["name"] : attr["units"]
                                        for attr in self.templateNDSDescription["networkAttributes"]
                                        if attr["usageType"].lower() == "cost"}
            distance_attribute_units = nds_cost_attribute_units[self.travelModeObject.distanceAttributeName]
            time_attribute_units = nds_cost_attribute_units[self.travelModeObject.timeAttributeName]

        #Convert the force hierarchy distance values in distance attribute units
        if tool_name == "GenerateServiceAreas":
            convert_units("forceHierarchyBeyondBreakDistanceValue", "forceHierarchyBeyondBreakDistanceValueUnits",
                          distance_attribute_units)
            convert_units("maximumBreakDistanceValue", "maximumBreakDistanceValueUnits", distance_attribute_units)
            convert_units("forceHierarchyBeyondBreakTimeValue", "forceHierarchyBeyondBreakTimeValueUnits",
                          time_attribute_units)
            convert_units("maximumBreakTimeValue", "maximumBreakTimeValueUnits", time_attribute_units)
        else:
            convert_units("forceHierarchyBeyondDistance", "forceHierarchyBeyondDistanceUnits",
                          distance_attribute_units)

        #For solve VRP return the values as required by a value table parameter
        if tool_name in ("SolveVehicleRoutingProblem", "EditVehicleRoutingProblem"):
            return [[self.VRP_SERVICE_CAPABILITIES_KEYWORDS[limit_name], infinity if value is None else value]
                    for limit_name, value in service_limits.iteritems()]
        else:
            return {self.SERVICE_CAPABILITIES_KEYWORDS[limit_name] : service_limits[limit_name]
                    for limit_name in service_limits}

    def _selectNetworkDataset(self, *analysis_inputs):
        #Determine the network dataset to use. If analysis region is specified use that as
        #the network dataset layer name
        connection_file = ""
        service_name = ""
        output_nds = ""
        if len(self.networkDatasets) == 1:
            output_nds = self.networkDatasets[0]
        elif self.analysisRegion:
            if self.analysisRegion in self.networkDatasets:
                output_nds = self.analysisRegion
            else:
                #Use the remote services
                where_clause = "{0} = '{1}'".format(self.EXTENT_FIELDS[0], self.analysisRegion)
                with arcpy.da.SearchCursor(self.networkDatasetExtents, self.EXTENT_FIELDS, where_clause) as cursor:
                    row = cursor.next()
                output_nds = row[0]
                connection_file_name, service_name = row[2].split(";", 1)
                desc_extent_layer = arcpy.Describe(self.networkDatasetExtents)
                connection_file = os.path.join(os.path.dirname(os.path.dirname(desc_extent_layer.catalogPath)),
                                               connection_file_name)
        else:
            #use extent polygons 
            if self.networkDatasetExtents:
                output_nds, connection_file, service_name = select_nds_extent_polygons(self.networkDatasetExtents,
                                                                                       self.EXTENT_FIELDS, 
                                                                                       analysis_inputs)
        
        self.connectionFile = connection_file
        #On server, the NDS layers are available as child layers within a group layer. Get the child layer name as the
        #network dataset layer name
        self.outputNDS = os.path.basename(output_nds)
        self.serviceName = service_name
        self.logger.debug(u"Network dataset used for analysis: {0}".format(self.outputNDS))

    def _getNetworkDatasetProperties(self):
        """Return the properties from all the network datasets as a ConfigParser object"""

        def get_network_properties(network):
            '''returns a dict containing network dataset properties'''
            property_names = ("time_attribute", "time_attribute_units", "distance_attribute",
                             "distance_attribute_units", "restrictions", "default_restrictions",
                             "attribute_parameter_values", "feature_locator_where_clause", "Extent",
                             "CatalogPath", "travel_modes", "default_custom_travel_mode", "walk_time_attribute",
                             "walk_time_attribute_units", "truck_time_attribute", "truck_time_attribute_units",
                             "non_walking_restrictions", "walking_restriction", "trucking_restriction",
                             "time_neutral_attribute", "time_neutral_attribute_units")
            restriction_usage_values = {"-1.0": "PROHIBITED",
                                        "5.0": "AVOID_HIGH",
                                        "2.0": "AVOID_MEDIUM",
                                        "1.3": "AVOID_LOW",
                                        "0.5" : "PREFER_MEDIUM",
                                        "0.8" : "PREFER_LOW",
                                        "0.2" : "PREFER_HIGH"
                                        }
            network_properties = dict.fromkeys(property_names)
            time_units = ('Minutes','Hours','Days', 'Seconds')
            populate_attribute_parameters = True
            desc = arcpy.Describe(network)
            nds_type = desc.networkType
            is_sdc_nds = (nds_type == 'SDC')
            default_time_attr = ""
            default_distance_attr = ""
            default_restriction_attrs = []
            time_costs = {}
            distance_costs = {}
            restrictions = []
            enable_hierarchy = False
            hierarchy = 0
            attribute_parameters = {}
            count = 0
            #Build a list of restriction, time and distance cost attributes
            #Get default attributes for geodatabase network datasets.
            attributes = desc.attributes
            for attribute in attributes:
                usage_type = attribute.usageType
                name = attribute.name
                unit = attribute.units
                use_by_default = attribute.useByDefault 
                if usage_type == "Restriction":
                    if use_by_default:
                        default_restriction_attrs.append(name)
                    restrictions.append(name)
                elif usage_type == "Cost":
                    #Determine if it is time based or distance based
                    if unit in time_units:
                        time_costs[name] = unit
                        if use_by_default:  
                            default_time_attr = name
                    else:
                        distance_costs[name] = unit
                        if use_by_default:
                            default_distance_attr = name
                else:
                    pass
                #populate all the attribute parameters and their default values.
                #Store this in a dict with key of row id and value as a list
                if populate_attribute_parameters:
                    parameter_count = attribute.parameterCount
                    if parameter_count:
                        for i in range(parameter_count):
                            param_name = getattr(attribute, "parameterName" + str(i))
                            param_default_value = None
                            if hasattr(attribute, "parameterDefaultValue" + str(i)):
                                param_default_value = str(getattr(attribute, "parameterDefaultValue" + str(i)))
                                if param_name.upper() == "RESTRICTION USAGE" and param_default_value in restriction_usage_values:
                                    param_default_value = restriction_usage_values[param_default_value]
                            count += 1
                            attribute_parameters[count] = (name, param_name, param_default_value)
        
            #Set the default time and distance attributes.
            first_time_cost_attribute = sorted(time_costs.keys())[0]
            if default_time_attr == "":
                #if there is no default use the first one in the list
                default_time_attr = first_time_cost_attribute 
            network_properties["time_attribute"] = default_time_attr
            network_properties["time_attribute_units"] = time_costs[default_time_attr]
            #Set the walk time and truck travel time attribute and their units. If the attributes with name
            #WalkTime and TruckTravelTime do not exist, use the first cost attribute
            walk_time_attribute = "WalkTime" if "WalkTime" in time_costs else first_time_cost_attribute
            network_properties["walk_time_attribute"] = walk_time_attribute
            network_properties["walk_time_attribute_units"] = time_costs[walk_time_attribute]
            truck_time_attribute = "TruckTravelTime" if "TruckTravelTime" in time_costs else first_time_cost_attribute
            network_properties["truck_time_attribute"] = truck_time_attribute
            network_properties["truck_time_attribute_units"] = time_costs[truck_time_attribute]
            time_neutral_attribute = "Minutes" if "Minutes" in time_costs else first_time_cost_attribute
            network_properties["time_neutral_attribute"] = time_neutral_attribute
            network_properties["time_neutral_attribute_units"] = time_costs[time_neutral_attribute]

            if default_distance_attr == "":
                #Use the last one in case a default is not set
                default_distance_attr = sorted(distance_costs.keys())[-1]
            network_properties["distance_attribute"] = default_distance_attr
            network_properties["distance_attribute_units"] = distance_costs[default_distance_attr]
        
            #Set complete restrictions, default restrictions and non-walking restrictions
            network_properties["restrictions"] = ";".join(restrictions)
            network_properties["default_restrictions"] = ";".join(default_restriction_attrs)
            network_properties["non_walking_restrictions"] = ";".join(fnmatch.filter(restrictions, "Driving*"))
            walking_restriction = "Walking" if "Walking" in restrictions else ""
            trucking_restriction = "Driving a Truck" if "Driving a Truck" in restrictions else ""
            network_properties["walking_restriction"] = walking_restriction
            network_properties["trucking_restriction"] = trucking_restriction

            #Set attribute parameters
            if populate_attribute_parameters and attribute_parameters:
                network_properties["attribute_parameter_values"] = pickle.dumps(attribute_parameters)
        
            #Update the feature locator where clause
            if is_sdc_nds:
                source_names = ["SDC Edge Source"]
            else:    
                all_source_names = [source.name for source in desc.sources]
                turn_source_names = [turn_source.name for turn_source in desc.turnSources]
                source_names = list(set(all_source_names) - set(turn_source_names))
            search_query = [('"' + source_name + '"', "#") for source_name in source_names]
            search_query = [" ".join(s) for s in search_query]
            network_properties["feature_locator_where_clause"] = ";".join(search_query)
        
            #store the extent
            extent = desc.Extent
            extent_coords = (str(extent.XMin),str(extent.YMin), str(extent.XMax),
                            str(extent.YMax))
            network_properties["Extent"] = pickle.dumps(extent_coords)
        
            #store the catalog path 
            network_properties["CatalogPath"] = desc.catalogPath

            #Store the travel modes in a dict with key as a two value tuple (travel mode type, isModeTimeBased) 
            #and value as travel mode name
            nds_travel_modes = {k.upper() : v for k,v in arcpy.na.GetTravelModes(desc.catalogPath).iteritems()}
            travel_modes = {}
            #esmp_travel_mode_names = ("Driving Time", "Driving Distance", "Trucking Time", "Trucking Distance",
            #                          "Walking Time", "Walking Distance")
            esmp_travel_mode_names = ("DRIVING TIME", "DRIVING DISTANCE", "TRUCKING TIME", "TRUCKING DISTANCE",
                                      "WALKING TIME", "WALKING DISTANCE", "RURAL DRIVING TIME", "RURAL DRIVING DISTANCE")
            for travel_mode_name in nds_travel_modes:
                nds_travel_mode = json.loads(unicode(nds_travel_modes[travel_mode_name]))
                travel_mode_impedance = nds_travel_mode["impedanceAttributeName"]
                is_impedance_time_based = None
                if travel_mode_impedance in time_costs:
                    is_impedance_time_based = True
                elif travel_mode_impedance in distance_costs:
                    is_impedance_time_based = False
                else:
                    continue
                if travel_mode_name in esmp_travel_mode_names:
                    travel_mode_type = travel_mode_name.split(" ")[0]
                else:
                    travel_mode_type = travel_mode_name
                travel_modes[(travel_mode_type, is_impedance_time_based)] = travel_mode_name

            network_properties["travel_modes"] = pickle.dumps(travel_modes)

            #store the travel mode that is used to set the custom travel mode settings parameters
            #default_custom_travel_mode_name = "Driving Time"
            default_custom_travel_mode_name = "DRIVING TIME"
            default_custom_travel_mode = nds_travel_modes.get(default_custom_travel_mode_name, {})
            if default_custom_travel_mode:
                default_custom_travel_mode = unicode(default_custom_travel_mode)
            network_properties["default_custom_travel_mode"] = default_custom_travel_mode
        
            return network_properties
        
        #Instance attributes set in this method
        self.parser = None
        self.templateNDS = ""
        
        #Write the network dataset properties file if it does not exist
        if not os.path.exists(self.networkDatasetPropertiesFile):
            parser = ConfigParser.SafeConfigParser() 
            for network in self.networkDatasets:
                network_props = get_network_properties(network)
                #nds_catalog_path = network_props.pop("CatalogPath")
                parser.add_section(network)
                for prop in sorted(network_props):
                    parser.set(network, prop, network_props[prop])

            self.logger.debug("Writing network dataset properties to {0}".format(self.networkDatasetPropertiesFile))
            with open(self.networkDatasetPropertiesFile, "w", 0) as config_file:
                parser.write(config_file)
        
        #return a parser object that has read the properties file
        self.parser = ConfigParser.SafeConfigParser()
        self.logger.debug("Reading network dataset properties from {0}".format(self.networkDatasetPropertiesFile))
        self.parser.read(self.networkDatasetPropertiesFile)
        self.templateNDS = self.parser.sections()[0]

    def _getToolParametersFromNDSProperties(self):
        '''Return a list of big button tool parameters whose values are stored in the network dataset properties file '''

        #Get the time attribute, distance attribute and feature locator where clause from config file
        nds_property_values = [] 
        for prop in self.NDS_PROPERTY_NAMES:
            option = prop.lower()
            if option in self.parser.options(self.outputNDS):
                option_value = self.parser.get(self.outputNDS, option)
                nds_property_values.append((prop, option_value))

        return  nds_property_values

    def _getNDSTravelModeJSON(self, travel_mode_name):
        '''Returns a stringified JSON for the travel mode name from the list of travel modes supported in the network
        dataset. If the travel mode name does not exist, an empty string is retured. The travel mode name lookup is 
        done in case insesitive manner.'''

        travel_mode = ""
        self.supportedTravelModeNames = []

        #look up for the travel mode name in the network dataset and return the travel mode json
        nds_travel_modes = self.templateNDSDescription.get("supportedTravelModes", [])
        for nds_travel_mode in nds_travel_modes:
            self.supportedTravelModeNames.append(nds_travel_mode["name"])
            if nds_travel_mode["name"].lower() == travel_mode_name.lower():
                travel_mode = json.dumps(nds_travel_mode, ensure_ascii=False)
                break
        else:
            travel_mode = ""
        if travel_mode:
            self.logger.debug(u"Returning travel mode JSON from the network dataset for travel mode name: {}".format(travel_mode_name))
        return travel_mode

    def _getPortalTravelModeJSON(self, travel_mode_name):
        '''Returns a stringified JSON for the travel mode name from the list of travel modes supported in the portal. 
        If the travel mode name does not exist, an empty string is retured. The travel mode name lookup is done in case
        insesitive manner.'''

        travel_mode = ""
        self.supportedTravelModeNames = []
        rest_info = get_rest_info()
        try: 
            if "owningSystemUrl" in rest_info:
                #Look up travel mode name using GetTravelModes routingUtilities service.
                portal_self = get_portal_self()
                if "helperServices" in portal_self:
                    routing_utilities_url = portal_self["helperServices"]["routingUtilities"]["url"]
                else:
                    #The server is federated, but something went wrong when determing the URL to the routingUtilities
                    #service. So look up travel mode name in the network dataset
                    travel_mode = self._getNDSTravelModeJSON(travel_mode_name)
                    return travel_mode
            else:
                #As the server is not federated, look up travel mode name in the network dataset
                travel_mode = self._getNDSTravelModeJSON(travel_mode_name)
                return travel_mode

            #Call GetTravelModes service using REST and get a dict of travel mode names and travel mode JSON
            gp_server_request_props = json.loads(arcpy.gp._arc_object.serverrequestproperties())
            token = gp_server_request_props.get("token", "")
            referer = gp_server_request_props.get("referer", "")

            get_travel_modes_url = u"{0}/GetTravelModes/execute".format(routing_utilities_url)
            request_parameters = {"token" : token}

            get_travel_modes_response = make_http_request(get_travel_modes_url, request_parameters, "gzip", referer)
            result_rows = get_travel_modes_response["results"][0]["value"]["features"]
            supported_travel_modes = {}
            for row in result_rows:
                attributes = row["attributes"]
                travel_mode_json = attributes["TravelMode"]
                self.supportedTravelModeNames.append(attributes["Name"])
                supported_travel_modes[attributes["Name"].upper()] = travel_mode_json
                supported_travel_modes[attributes["AltName"].upper()] = travel_mode_json 
            travel_mode = supported_travel_modes.get(travel_mode_name.upper(), "")
        except Exception as ex:
            self.logger.warning("Failed to get a list of supported travel modes from the portal")
            if self.logger.DEBUG:
                self._handleException()
        if travel_mode:
            self.logger.debug(u"Returning travel mode JSON from the portal for travel mode name: {}".format(travel_mode_name))
        return travel_mode

    def _selectTravelMode(self):
        '''Select a travel mode for the analysis'''

        #Instance attributes that are set in this method
        self.travelModeObject = None
        self.portalTravelMode = None
        self.customTravelModeDistanceAttribute = ""
        self.customTravelModeTimeAttribute = ""
        self.customTravelModeImpedanceAttribute = ""
        self.walkingRestriction = ""
        
        #Create a mapping of cost attributes from the network dataset and the values of impedance parameter
        #For all network datasets, assume the cost attributes to be same as those that are found in the first section
        impedance_parameter_mappings = {
            "Drive Time" : self.parser.get(self.templateNDS, "time_attribute"),
            "Truck Time" : self.parser.get(self.templateNDS, "truck_time_attribute"),
            "Walk Time" : self.parser.get(self.templateNDS, "walk_time_attribute"),
            "Travel Distance" : self.parser.get(self.templateNDS, "distance_attribute"),
        }
        #Get network dataset travel mode name
        #If the travel mode is JSON string pass the JSON to the big button tool
        nds_travel_modes = pickle.loads(self.parser.get(self.templateNDS, "travel_modes"))
        self.portalTravelMode = nds_travel_modes.get((self.travelMode.upper(), self.isMeasurementUnitsTimeBased),
                                                     self.travelMode)

        #If travel mode is not a JSON look for the travel mode name in portal. 
        if self.isCustomTravelMode:
            self.portalTravelMode = "CUSTOM"
        else:
            try: 
                self.travelModeObject = arcpy.na.TravelMode(self.portalTravelMode)    
            except ValueError as ex:
                #Get the travel mode JSON from the portal based on its name
                self.portalTravelMode = self._getPortalTravelModeJSON(self.portalTravelMode)
                if self.portalTravelMode:
                    self.travelModeObject = arcpy.na.TravelMode(self.portalTravelMode)
                else:
                    valid_travel_mode_names = u" | ".join(sorted(self.supportedTravelModeNames) + ["Custom"])
                    arcpy.AddIDMessage("ERROR", 30158, self.travelMode, valid_travel_mode_names)
                    raise InputError
            #If the travel mode has a 0 simplification tolerance, set it to None with unknown units
            portal_travel_mode = json.loads(self.portalTravelMode, "utf-8")
            if portal_travel_mode["simplificationTolerance"] == 0:
                portal_travel_mode["simplificationTolerance"] = None
                portal_travel_mode["simplificationToleranceUnits"] = "esriUnknownUnits"
                self.portalTravelMode = json.dumps(portal_travel_mode, ensure_ascii=False)

        travel_mode_restrictions = self.travelModeObject.restrictions if self.travelModeObject else []
        self.logger.debug(u"Travel Mode used for the analysis: {0}".format(self.portalTravelMode))

        #For custom travel mode always assume a fixed distance attribute and a fixed time attribute if impedance is
        #distance based
        self.customTravelModeDistanceAttribute = impedance_parameter_mappings["Travel Distance"]
        self.customTravelModeTimeAttribute = impedance_parameter_mappings["Drive Time"]
        self.walkingRestriction = self.parser.get(self.templateNDS, "walking_restriction")
        trucking_restriction = self.parser.get(self.templateNDS, "trucking_restriction")
        is_custom_travel_mode_impedance_time_based = False
        self.customTravelModeImpedanceAttribute = self.customTravelModeDistanceAttribute
        if self.impedance != "Travel Distance":
            self.customTravelModeTimeAttribute = impedance_parameter_mappings[self.impedance]
            self.customTravelModeImpedanceAttribute = self.customTravelModeTimeAttribute
            is_custom_travel_mode_impedance_time_based = True

        ##Check for failure conditions when using custom travel modes
        non_walking_restrictions = self.parser.get(self.templateNDS, "non_walking_restrictions").split(";")
        if self.isCustomTravelMode:
            #Fail if break units and impedance are not compatible
            if self.measurementUnits:
                if self.isMeasurementUnitsTimeBased:
                    if not is_custom_travel_mode_impedance_time_based:
                        arcpy.AddIDMessage("ERROR", 30148, self.measurementUnits, self.impedance)
                        raise InputError
                else:
                    if is_custom_travel_mode_impedance_time_based:
                        arcpy.AddIDMessage("ERROR", 30148, self.measurementUnits, self.impedance)
                        raise InputError
            #Fail if walking and any of "Driving *" restrictions are used
            if set(self.restrictions).intersection(set(non_walking_restrictions)):
                if self.walkingRestriction in self.restrictions:
                    arcpy.AddIDMessage("ERROR", 30147, ", ".join(non_walking_restrictions))
                    raise InputError
        else:
            #Fail if walking and any of "Driving *" restrictions are used
            if set(travel_mode_restrictions).intersection(set(non_walking_restrictions)):
                if self.walkingRestriction in travel_mode_restrictions:
                    arcpy.AddIDMessage("ERROR", 30158, self.travelModeObject.name)
                    arcpy.AddIDMessage("ERROR", 30147, ", ".join(non_walking_restrictions))
                    raise InputError
    
    def _checkWalkingExtent(self, *analysis_inputs):
        '''When using Walking restriction, fail if inputs are more than maximum supported miles apart '''

        #nau.max_distance_between points returns the distance in meters. So convert to miles
        max_distance_inputs = 0
        if self.isCustomTravelMode:
            if self.walkingRestriction in self.restrictions:
                max_distance_inputs = nau.max_distance_between_points(analysis_inputs) * self.METER_TO_MILES
        else:
            travel_mode_type = "OTHER"
            if hasattr(self.travelModeObject, "type"):
                travel_mode_type = self.travelModeObject.type
            if self.walkingRestriction in self.travelModeObject.restrictions or travel_mode_type == "WALK":
                max_distance_inputs = nau.max_distance_between_points(analysis_inputs) * self.METER_TO_MILES

        if max_distance_inputs > self.MAX_WALKING_MODE_DISTANCE_MILES:
            arcpy.AddIDMessage("ERROR", 30145, self.MAX_WALKING_MODE_DISTANCE_MILES,
                               int(self.MAX_WALKING_MODE_DISTANCE_MILES / self.METER_TO_MILES / 1000))
            raise InputError
    
    def _checkMaxOutputFeatures(self, analysis_output, error_message_code=30142):
        '''Check if the count of output features exceeds the maximum number of records that can be successfully 
        returned by the service'''

        output_features_count = int(arcpy.management.GetCount(analysis_output).getOutput(0))
        if output_features_count > self.maxFeatures:
            arcpy.AddIDMessage("ERROR", error_message_code, output_features_count, self.maxFeatures)
            raise arcpy.ExecuteError

    def  _logToolExecutionMessages(self):
        '''Log messages from execution of remote tool or big button tool'''

        result_severity = self.toolResult.maxSeverity
        warning_messages = self.toolResult.getMessages(1)
        error_messages = self.toolResult.getMessages(2)
        #for remote tools executed synchronously, maxSeverity and getMessages is determined using arcpy
        if result_severity == -1:
            result_severity = arcpy.GetMaxSeverity()
            warning_messages = arcpy.GetMessages(1)
            error_messages = arcpy.GetMessages(2)
        #print error and warning messages
        if result_severity == 1:
            #Do not output the WARNING 000685 message (empty route edges messages) as they will be always empty
            if self.__class__.__name__ == "SolveLocationAllocation":
                for msg in warning_messages.split("\n"):
                    if not msg.startswith("WARNING 000685:"):
                        self.logger.warning(msg)
            else:
                self.logger.warning(warning_messages)
        elif result_severity == 0:
            if self.logger.DEBUG:
                info_messages = self.toolResult.getMessages()
                if not info_messages:
                    #For remote tool executed synchoronously, get messages from arcpy
                    info_messages = arcpy.GetMessages()
                self.logger.debug(info_messages)
        else:
            #Tool failed. Add warning and error messages and raise exception
            self.logger.warning(warning_messages)
            self.logger.error(error_messages)
            raise InputError
               
    def _handleInputErrorException(self, ex):
        '''Exception handler for InputError'''

        self.solveSucceeded = False
        #Handle errors due to invalid inputs
        self.logger.error(ex.message)
    
    def _handleArcpyExecuteErrorException(self):
        '''Exeception handler for arcpy.ExecuteError'''

        self.solveSucceeded = False
        #Handle GP exceptions
        if self.logger.DEBUG:
            #Get the line number at which the GP error occurred    
            tb = sys.exc_info()[2]
            self.logger.error(u"A geoprocessing error occurred in file {0}, line {1}".format(__file__,
                                                                                                tb.tb_lineno))
        else:
            self.logger.error("A geoprocessing error occurred.")
        for msg in arcpy.GetMessages(1).split("\n"):
            self.logger.warning(msg)
        for msg in arcpy.GetMessages(2).split("\n"):
            self.logger.error(msg)

    def _handleException(self):
        '''handler for generic Exception'''
        self.solveSucceeded = False
        #Handle python errors
        if self.logger.DEBUG:
            #Get a nicely formatted traceback object except the first line.
            msgs = traceback.format_exception(*sys.exc_info())[1:]
            msgs[0] = "A python error occurred in " + msgs[0].lstrip()
            for msg in msgs:
                self.logger.error(msg.strip())
        else:
            self.logger.error("A python error occurred.")

    def _executeBigButtonTool(self, tool_parameters):
        '''Execute the big button tool and return the tool result as an instance attribute'''
        
        #Call the big button tool
        tool = getattr(arcpy, self.TOOL_NAME)
        if self.logger.DEBUG:
            self.logger.debug("uParameters passed when executing {0} tool".format(self.TOOL_NAME))
            for param_name in sorted(tool_parameters):
                self.logger.debug(u"{0}: {1}".format(param_name, tool_parameters[param_name]))
        self.toolResult = tool(**tool_parameters)
        if self.logger.DEBUG:
            self.logger.debug(u"{0} tool {1}".format(self.TOOL_NAME,
                                                        self.toolResult.getMessage(self.toolResult.messageCount - 1)))
                
class FindRoutes(NetworkAnalysisService):
    '''FindRoutes geoprocessing service'''

    OUTPUT_ROUTES_NAME = "Routes"
    OUTPUT_ROUTE_EDGES_NAME = "RouteEdges"
    OUTPUT_DIRECTIONS_NAME = "Directions"
    OUTPUT_STOPS_NAME = "Stops"
    ORDERING_KEYWORDS = {
        "Preserve First and Last" : "PRESERVE_BOTH",
        "Preserve First" : "PRESERVE_FIRST",
        "Preserve Last" : "PRESERVE_LAST",
        "Preserve None": "PRESERVE_NONE",
    }
    EXTENT_FIELDS = NetworkAnalysisService.EXTENT_FIELDS[:]
    EXTENT_FIELDS[2] =  "GPRouteService"
    #MAX_FEATURES = 1000000
    REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX = 14
    
    TOOL_NAME = "FindRoutes_na"
    HELPER_SERVICES_KEY = "asyncRoute"
    
    def __init__(self, *args, **kwargs):
        '''Constructor'''

        #Call the base class constructor to sets the common tool parameters as instance attributes
        super(FindRoutes, self).__init__(*args, **kwargs)

        #Store tool parameters as instance attributes
        self.stops = kwargs.get("Stops", None)
        self.reorderStops = kwargs.get("Reorder_Stops_to_Find_Optimal_Routes", None)
        self.orderingType = kwargs.get("Preserve_Terminal_Stops", None)
        self.returnToStart = kwargs.get("Return_to_Start", None)
        self.useTimeWindows = kwargs.get("Use_Time_Windows", None)
        self.timeZoneForTimeWindows = kwargs.get("Time_Zone_for_Time_Windows", None)
        self.routeShape = kwargs.get("Route_Shape", None)
        self.routeLineSimplicationTolerance = kwargs.get("Route_Line_Simplification_Tolerance", None)
        #Set simplification tolerance to None if value is 0
        if str_to_float(self.routeLineSimplicationTolerance.split(" ")[0]) == 0:
            self.routeLineSimplicationTolerance = None
        self.populateRouteEdges = kwargs.get("Populate_Route_Edges", None)
        self.populateDirections = kwargs.get("Populate_Directions", None)
        self.directionsLanguage = kwargs.get("Directions_Language", None)
        self.directionsDistanceUnits = kwargs.get("Directions_Distance_Units", None)
        self.directionsStyleName = kwargs.get("Directions_Style_Name", None)
        self.saveRouteData = kwargs.get("Save_Route_Data", None)

        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))
                      
        #derived outputs
        self.outputRoutes = os.path.join(self.outputGeodatabase, self.OUTPUT_ROUTES_NAME)
        self.outputRouteEdges = os.path.join(self.outputGeodatabase, self.OUTPUT_ROUTE_EDGES_NAME)
        self.outputDirections = os.path.join(self.outputGeodatabase, self.OUTPUT_DIRECTIONS_NAME)
        self.outputStops = os.path.join(self.outputGeodatabase, self.OUTPUT_STOPS_NAME)
        self.outputRouteData = ""
        
    def execute(self):
        '''Main execution logic'''
        try:
            arcpy.CheckOutExtension("network")

            #Get the properties for all network datasets from a propeties file. 
            self._getNetworkDatasetProperties()

            #Select the travel mode
            self._selectTravelMode()

            #Get the values for big button tool parameters that are used as constraints
            service_limits = self._getServiceCapabilities()
            self.logger.debug("Service Limits: {0}".format(service_limits))

            #Define values for big button tool parameters that are not specified from the service
            constant_params = [('Maximum_Snap_Tolerance', '20 Kilometers'),
                               ('Accumulate_Attributes', []),
                               ('Output_Geodatabase', self.outputGeodatabase),
                               ('Output_Routes_Name', self.OUTPUT_ROUTES_NAME),
                               ('Output_Directions_Name', self.OUTPUT_DIRECTIONS_NAME),
                               ('Output_Stops_Name', self.OUTPUT_STOPS_NAME),
                               ('Output_Route_Edges_Name', self.OUTPUT_ROUTE_EDGES_NAME),
                               ]

            #Create a list of user defined parameter names and their values
            user_parameters = [('Stops', self.stops),
                               ('Measurement_Units', self.measurementUnits),
                               ('Reorder_Stops_to_Find_Optimal_Routes', self.reorderStops),
                               ('Preserve_Terminal_Stops', self.ORDERING_KEYWORDS[self.orderingType]),
                               ('Return_to_Start', self.returnToStart),
                               ('Use_Time_Windows', self.useTimeWindows),
                               ('Time_Zone_for_Time_Windows', self.TIME_ZONE_USAGE_KEYWORDS[self.timeZoneForTimeWindows]),
                               ('Use_Hierarchy_in_Analysis', self.useHierarchy),
                               ('Time_of_Day', self.timeOfDay),
                               ('Time_Zone_for_Time_of_Day', self.TIME_ZONE_USAGE_KEYWORDS[self.timeZoneUsage]),
                               ('UTurn_Policy', self.UTURN_KEYWORDS[self.uTurnAtJunctions]),
                               ('Route_Shape', self.ROUTE_SHAPE_KEYWORDS[self.routeShape]),
                               ('Route_Line_Simplification_Tolerance', self.routeLineSimplicationTolerance),
                               ('Point_Barriers', self.pointBarriers),
                               ('Line_Barriers', self.lineBarriers),
                               ('Polygon_Barriers', self.polygonBarriers),
                               ('Restrictions', self.restrictions),
                               ('Attribute_Parameter_Values', self.attributeParameterValues),
                               ('Populate_Route_Edges', self.populateRouteEdges),
                               ('Populate_Directions', self.populateDirections),
                               ('Directions_Language', self.directionsLanguage),
                               ('Directions_Distance_Units', self.directionsDistanceUnits),
                               ('Directions_Style_Name', self.directionsStyleName),
                               ('Travel_Mode', self.portalTravelMode),
                               ('Save_Output_Network_Analysis_Layer', self.saveLayerFile),
                               ('Overrides', self.overrides),
                               ('Save_Route_Data', self.saveRouteData),
                               ]
   
            #Fail if no stops are given
            stop_count = int(arcpy.management.GetCount(self.stops).getOutput(0))
            if stop_count < 2:
                arcpy.AddIDMessage("ERROR", 30134)
                raise InputError
    
            #Determine the network dataset to use. If analysis region is specified use that as
            #the network dataset layer name
            self._selectNetworkDataset(self.stops)

            if self.connectionFile:
                #Add remote tool
                self.logger.debug(u"Adding remote service {0} from {1}".format(self.serviceName, self.connectionFile))
                remote_tool_name, remote_toolbox = add_remote_toolbox(self.connectionFile, self.serviceName)

                #specify parameter values for the remote tool
                #need to pass boolean values for boolean parameters when calling the remote service
                task_params = [self.stops, self.measurementUnits, "#", self.reorderStops,
                               self.orderingType, self.returnToStart, self.useTimeWindows, self.timeOfDay,
                               self.timeZoneUsage, self.uTurnAtJunctions, self.pointBarriers, self.lineBarriers,
                               self.polygonBarriers, self.useHierarchy, "#", self.attributeParameterValues,
                               self.routeShape, self.routeLineSimplicationTolerance, self.populateRouteEdges,
                               self.populateDirections, self.directionsLanguage, self.directionsDistanceUnits,
                               self.directionsStyleName, self.portalTravelMode, self.impedance,
                               self.timeZoneForTimeWindows, self.saveLayerFile, self.overrides, self.saveRouteData]

                #remove any unsupported restriction parameters when using a custom travel mode
                if self.isCustomTravelMode:
                    remote_tool_param_info = arcpy.GetParameterInfo(remote_tool_name)
                    remote_tool_restriction_param = remote_tool_param_info[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX]
                    task_params[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX] = get_valid_restrictions_remote_tool(remote_tool_restriction_param,
                                                                                                                self.restrictions)
                #execute the remote tool
                self.toolResult = execute_remote_tool(remote_toolbox, remote_tool_name, task_params)

                #report errors and exit in case the remote tool failed.
                if self.toolResult.maxSeverity == 2:
                    error_messages = self.toolResult.getMessages(1) + self.toolResult.getMessages(2)
                    raise InputError(error_messages)
                else:
                    #Save the results
                    solve_status = self.toolResult.getOutput(0)
                    if solve_status.lower() == 'true':
                        self.solveSucceeded = True
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(1), self.outputRoutes)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(2), self.outputRouteEdges)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(3), self.outputDirections)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(4), self.outputStops)
                    self.outputLayer = self.toolResult.getOutput(5)
                    self.outputRouteData = self.toolResult.getOutput(6)
            else:
        
                #Add the network dataset that we wish to use.    
                user_parameters.append(("Network_Dataset", self.outputNDS))
        
                #Get the time attribute, distance attribute and feature locator where clause from config file
                nds_property_values = self._getToolParametersFromNDSProperties()
        
                #Create a dict that contains all the tool parameters and call the tool.
                tool_parameters = dict(nds_property_values + constant_params + user_parameters)
                tool_parameters.update(service_limits)
                if self.isCustomTravelMode:
                    tool_parameters["Time_Attribute"] = self.customTravelModeTimeAttribute
                    tool_parameters["Distance_Attribute"] = self.customTravelModeDistanceAttribute

                #Update time attribute and distance attribute when using custom travel mode. 
                self._checkWalkingExtent(self.stops)

                #Call the big button tool
                self._executeBigButtonTool(tool_parameters)
                
                #get outputs from the result
                solve_status = self.toolResult.getOutput(0)
                if solve_status.lower() == 'true':
                    self.solveSucceeded = True
                self.outputRoutes = self.toolResult.getOutput(1)
                self.outputRouteEdges = self.toolResult.getOutput(2)
                self.outputDirections = self.toolResult.getOutput(3)
                self.outputStops = self.toolResult.getOutput(4)
                self.outputLayer = self.toolResult.getOutput(5)
                self.outputRouteData = self.toolResult.getOutput(6)
    
            #Fail if the count of features in route edges or directions exceeds the maximum number of records
            #returned by the service
            if self.populateDirections:
                self._checkMaxOutputFeatures(self.outputDirections)
                #Generalize the directions features
                arcpy.edit.Generalize(self.outputDirections, self.routeLineSimplicationTolerance)
            if self.populateRouteEdges:
                self._checkMaxOutputFeatures(self.outputRouteEdges, 30143)
                #Generalize the route edges
                arcpy.edit.Generalize(self.outputRouteEdges, self.routeLineSimplicationTolerance)
            
            #Log messages from execution of remote or big button tool
            self._logToolExecutionMessages()
            
            #Add metering and royalty messages
            #numObjects = number of routes           
            num_objects = int(arcpy.management.GetCount(self.outputRoutes).getOutput(0))
            #Include whether we solved TSP in the task name
            if self.reorderStops:
                metering_task_name = "tsp::Route"
            else:
                metering_task_name = "simple::Route"
            if num_objects:
                arcpy.gp._arc_object.LogUsageMetering(5555, metering_task_name, num_objects)
                arcpy.gp._arc_object.LogUsageMetering(9999, self.outputNDS, num_objects)    

        except InputError as ex:
            self._handleInputErrorException(ex)
        except arcpy.ExecuteError:
            self._handleArcpyExecuteErrorException()
        except Exception as ex:
            self._handleException()

        return

class FindClosestFacilities(NetworkAnalysisService):
    '''FindClosestFacilities geoprocessing service'''

    OUTPUT_ROUTES_NAME = "Routes"
    OUTPUT_DIRECTIONS_NAME = "Directions"
    OUTPUT_FACILITIES_NAME = "ClosestFacilities"
    TIME_OF_DAY_USAGE_KEYWORDS = {
        "Start Time" : "START_TIME", 
        "End Time" : "END_TIME",
        "Not Used" : "NOT_USED"
    }
    TRAVEL_DIR_KEYWORDS = {
        "Facility to Incident" : "TRAVEL_FROM",
        "Incident to Facility" : "TRAVEL_TO"
    }
    EXTENT_FIELDS = NetworkAnalysisService.EXTENT_FIELDS[:]
    EXTENT_FIELDS[2] = "GPClosestFacilityService"
    #MAX_FEATURES = 1000000
    REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX = 14
    
    TOOL_NAME = "FindClosestFacilities_na"
    HELPER_SERVICES_KEY = "asyncClosestFacility"

    def __init__(self, *args, **kwargs):
        '''Constructor'''

        #Call the base class constructor to sets the common tool parameters as instance attributes
        super(FindClosestFacilities, self).__init__(*args, **kwargs)

        #Store tool parameters as instance attributes
        self.incidents = kwargs.get("Incidents", None)
        self.facilities = kwargs.get("Facilities", None)
        self.facilitiesToFind = kwargs.get("Number_of_Facilities_to_Find", None)
        
        self.cutoff = kwargs.get("Cutoff", None)
        if self.cutoff:
            try:
                self.cutoff = str_to_float(self.cutoff)
            except ValueError as ex:
                self.cutoff = None

        self.travelDirection = kwargs.get("Travel_Direction", None)
        self.timeOfDayUsage = kwargs.get("Time_of_Day_Usage", None)
        self.routeShape = kwargs.get("Route_Shape", None)
        self.routeLineSimplicationTolerance = kwargs.get("Route_Line_Simplification_Tolerance", None)
        #Set simplification tolerance to None if value is 0
        if str_to_float(self.routeLineSimplicationTolerance.split(" ")[0]) == 0:
            self.routeLineSimplicationTolerance = None
        self.populateDirections = kwargs.get("Populate_Directions", None)
        self.directionsLanguage = kwargs.get("Directions_Language", None)
        self.directionsDistanceUnits = kwargs.get("Directions_Distance_Units", None)
        self.directionsStyleName = kwargs.get("Directions_Style_Name", None)
        self.saveRouteData = kwargs.get("Save_Route_Data", None)

        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))
        
        #derived outputs
        self.outputRoutes = os.path.join(self.outputGeodatabase, self.OUTPUT_ROUTES_NAME)
        self.outputDirections = os.path.join(self.outputGeodatabase, self.OUTPUT_DIRECTIONS_NAME)
        self.outputFacilities = os.path.join(self.outputGeodatabase, self.OUTPUT_FACILITIES_NAME)
        self.outputRouteData = ""

    def execute(self):
        '''Main execution logic'''

        try:
            arcpy.CheckOutExtension("network")

            #Get the properties for all network datasets from a propeties file. 
            self._getNetworkDatasetProperties()

            #Select the travel mode
            self._selectTravelMode()

            #Get the values for big button tool parameters that are used as constraints
            service_limits = self._getServiceCapabilities()
            self.logger.debug("Service Limits: {0}".format(service_limits))

            #Define values for big button tool parameters that are not specified from the service
            constant_params = [('Maximum_Snap_Tolerance', '20 Kilometers'),
                               ('Accumulate_Attributes', []),
                               ('Output_Geodatabase', self.outputGeodatabase),
                               ('Output_Routes_Name', self.OUTPUT_ROUTES_NAME),
                               ('Output_Directions_Name', self.OUTPUT_DIRECTIONS_NAME),
                               ('Output_Closest_Facilities_Name', self.OUTPUT_FACILITIES_NAME),
                               ]

            #Create a list of user defined parameter names and their values
            user_parameters = [('Facilities', self.facilities),
                               ('Incidents', self.incidents),
                               ('Measurement_Units', self.measurementUnits),
                               ('Number_of_Facilities_to_Find', self.facilitiesToFind),
                               ('Travel_Direction', self.TRAVEL_DIR_KEYWORDS[self.travelDirection]),
                               ('Default_Cutoff', self.cutoff),
                               ('Use_Hierarchy_in_Analysis', self.useHierarchy),
                               ('Time_of_Day', self.timeOfDay),
                               ('Time_of_Day_Usage', self.TIME_OF_DAY_USAGE_KEYWORDS[self.timeOfDayUsage]),
                               ('Time_Zone_for_Time_of_Day', self.TIME_ZONE_USAGE_KEYWORDS[self.timeZoneUsage]),
                               ('UTurn_Policy', self.UTURN_KEYWORDS[self.uTurnAtJunctions]),
                               ('Route_Shape', self.ROUTE_SHAPE_KEYWORDS[self.routeShape]),
                               ('Route_Line_Simplification_Tolerance', self.routeLineSimplicationTolerance),
                               ('Point_Barriers', self.pointBarriers),
                               ('Line_Barriers', self.lineBarriers),
                               ('Polygon_Barriers', self.polygonBarriers),
                               ('Restrictions', self.restrictions),
                               ('Attribute_Parameter_Values', self.attributeParameterValues),
                               ('Populate_Directions', self.populateDirections),
                               ('Directions_Language', self.directionsLanguage),
                               ('Directions_Distance_Units', self.directionsDistanceUnits),
                               ('Directions_Style_Name', self.directionsStyleName),
                               ('Travel_Mode', self.portalTravelMode),
                               ('Save_Output_Network_Analysis_Layer', self.saveLayerFile),
                               ('Overrides', self.overrides),
                               ('Save_Route_Data', self.saveRouteData),
                               ]

           
            #Fail if no incidents or facilities are given
            incident_count = int(arcpy.management.GetCount(self.incidents).getOutput(0))
            facility_count = int(arcpy.management.GetCount(self.facilities).getOutput(0))
            if incident_count == 0 or facility_count == 0:
                arcpy.AddIDMessage("ERROR", 30125)
                raise InputError

            #Determine the network dataset to use. If analysis region is specified use that as
            #the network dataset layer name
            self._selectNetworkDataset(self.incidents, self.facilities)

            if self.connectionFile:
                #Add remote tool
                self.logger.debug(u"Adding remote service {0} from {1}".format(self.serviceName, self.connectionFile))
                remote_tool_name, remote_toolbox = add_remote_toolbox(self.connectionFile, self.serviceName)

                #specify parameter values for the remote tool
                #need to pass boolean values for boolean parameters when calling the remote service
                task_params = [self.incidents, self.facilities, self.measurementUnits, "#", self.facilitiesToFind,
                               self.cutoff, self.travelDirection, self.useHierarchy, self.timeOfDay,
                               self.timeOfDayUsage, self.uTurnAtJunctions, self.pointBarriers, self.lineBarriers,
                               self.polygonBarriers, "#", self.attributeParameterValues, self.routeShape,
                               self.routeLineSimplicationTolerance, self.populateDirections, self.directionsLanguage,
                               self.directionsDistanceUnits, self.directionsStyleName, self.timeZoneUsage,
                               self.portalTravelMode, self.impedance, self.saveLayerFile, self.overrides,
                               self.saveRouteData]

                #remove any unsupported restriction parameters when using a custom travel mode
                if self.isCustomTravelMode:
                    remote_tool_param_info = arcpy.GetParameterInfo(remote_tool_name)
                    remote_tool_restriction_param = remote_tool_param_info[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX]
                    task_params[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX] = get_valid_restrictions_remote_tool(remote_tool_restriction_param,
                                                                                                                self.restrictions)
                #execute the remote tool
                self.toolResult = execute_remote_tool(remote_toolbox, remote_tool_name, task_params)

                #report errors and exit in case the remote tool failed.
                if self.toolResult.maxSeverity == 2:
                    error_messages = self.toolResult.getMessages(1) + self.toolResult.getMessages(2)
                    raise InputError(error_messages)
                else:
                    #Save the results
                    solve_status = self.toolResult.getOutput(2)
                    if solve_status.lower() == 'true':
                        self.solveSucceeded = True
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(0), self.outputRoutes)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(1), self.outputDirections)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(3), self.outputFacilities)
                    self.outputLayer = self.toolResult.getOutput(4)
                    self.outputRouteData = self.toolResult.getOutput(5) 
            
            else:
        
                #Add the network dataset that we wish to use.    
                user_parameters.append(("Network_Dataset", self.outputNDS))
        
                #Get the time attribute, distance attribute and feature locator where clause from config file
                nds_property_values = self._getToolParametersFromNDSProperties()
        
                #Create a dict that contains all the tool parameters and call the tool.
                tool_parameters = dict(nds_property_values + constant_params + user_parameters)
                tool_parameters.update(service_limits)
                if self.isCustomTravelMode:
                    tool_parameters["Time_Attribute"] = self.customTravelModeTimeAttribute
                    tool_parameters["Distance_Attribute"] = self.customTravelModeDistanceAttribute

                #Update time attribute and distance attribute when using custom travel mode. 
                self._checkWalkingExtent(self.incidents, self.facilities)

                #Call the big button tool
                self._executeBigButtonTool(tool_parameters)
                
                #get outputs from the result
                solve_status = self.toolResult.getOutput(0)
                if solve_status.lower() == 'true':
                    self.solveSucceeded = True
                self.outputRoutes = self.toolResult.getOutput(1)
                self.outputDirections = self.toolResult.getOutput(2)
                self.outputFacilities = self.toolResult.getOutput(3)
                self.outputLayer = self.toolResult.getOutput(4)
                self.outputRouteData = self.toolResult.getOutput(5)
    
            #Fail if the count of features in directions exceeds the maximum number of records returned by the service
            if self.populateDirections:
                self._checkMaxOutputFeatures(self.outputDirections)
                #Generalize the directions features
                arcpy.edit.Generalize(self.outputDirections, self.routeLineSimplicationTolerance)
            
            
            #Log messages from execution of remote or big button tool
            self._logToolExecutionMessages()
            
            #Add metering and royalty messages
            #numObjects = number of routes           
            num_objects = int(arcpy.management.GetCount(self.outputRoutes).getOutput(0))            
            if num_objects:
                arcpy.gp._arc_object.LogUsageMetering(5555, self.__class__.__name__, num_objects)
                arcpy.gp._arc_object.LogUsageMetering(9999, self.outputNDS, num_objects)

        except InputError as ex:
            self._handleInputErrorException(ex)
        except arcpy.ExecuteError:
            self._handleArcpyExecuteErrorException()
        except Exception as ex:
            self._handleException()

        return

class GenerateServiceAreas(NetworkAnalysisService):
    '''GenerateServiceAreas geoprocessing service'''

    TRAVEL_DIR_KEYWORDS = {
        "Away From Facility" : "TRAVEL_FROM",
        "Towards Facility" : "TRAVEL_TO"
    }
    MERGE_POLYGONS_KEYWORDS = {
        "Overlapping" : "NO_MERGE", 
        "Not Overlapping" : "NO_OVERLAP",
        "Merge by Break Value" : "MERGE",
    }
    EXTENT_FIELDS = NetworkAnalysisService.EXTENT_FIELDS[:]
    EXTENT_FIELDS[2] = "GPServiceAreaService"
    REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX = 16
    #Use this factor to convert max break time and max break distance to the max time and distance for detailed polygons
    MAX_DETAILED_POLYGONS_FACTOR = 0.05
    #MAX_FEATURES = 10000
    MILES_TO_KM = 1.60934
    TOOL_NAME = "GenerateServiceAreas_na"
    HELPER_SERVICES_KEY = "asyncServiceArea"

    def __init__(self, *args, **kwargs):
        '''Constructor'''

        #Call the base class constructor to sets the common tool parameters as instance attributes
        super(GenerateServiceAreas, self).__init__(*args, **kwargs)

        #Store tool parameters as instance attributes
        self.facilities = kwargs.get("Facilities", None)
        self.breakValues = kwargs.get("Break_Values", None)
        self.travelDirection = kwargs.get("Travel_Direction", None)
        self.polygonType = kwargs.get("Polygons_for_Multiple_Facilities", None)
        self.overlapType = kwargs.get("Polygon_Overlap_Type", None)
        self.detailedPolygons = kwargs.get("Detailed_Polygons", None)
        self.trimDistance = kwargs.get("Polygon_Trim_Distance", None)
        self.simplificationTolerance = kwargs.get("Polygon_Simplification_Tolerance", None)
        #Set simplification tolerance to None if value is 0
        if str_to_float(self.simplificationTolerance.split(" ")[0]) == 0:
            self.simplificationTolerance = None
        
        #outputs and derived outputs
        self.outputServiceAreas = kwargs.get("Service_Areas", os.path.join("in_memory", "ServiceAreas"))

        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))
    
    def execute(self):
        '''main execution logic of the service'''

        try:
            arcpy.CheckOutExtension("network")

            #Get the properties for all network datasets from a propeties file. 
            self._getNetworkDatasetProperties()

            #Select a travel mode
            self._selectTravelMode()

            #Get the values for big button tool parameters that are used as constraints
            service_limits = self._getServiceCapabilities()
            self.logger.debug("Service Limits: {0}".format(service_limits))

            #Determine the max break time and break distance for which to support detailed polygons with exact solve
            #based on the max break time and max break distance values
            max_break_time = service_limits["Maximum_Break_Time_Value"]
            max_break_distance = service_limits["Maximum_Break_Distance_Value"]
            max_break_time_detailed_polys = None
            max_break_distance_detailed_polys = None
            enforce_detailed_polys_limit = False
            if max_break_time:
                max_break_time_detailed_polys = max_break_time * self.MAX_DETAILED_POLYGONS_FACTOR
            if max_break_distance:
                max_break_distance_detailed_polys = max_break_distance * self.MAX_DETAILED_POLYGONS_FACTOR
            if max_break_time_detailed_polys or max_break_distance_detailed_polys:
                enforce_detailed_polys_limit = True
        
            #Define big tool parameters that are not set by the service
            constant_params = [
                ('Maximum_Snap_Tolerance', '20 Kilometers'),
                ('Exclude_Restricted_Portions_of_the_Network', 'EXCLUDE'),
                ]

            #Create a list of user defined parameter names and their values
            user_parameters = [
                ('Facilities', self.facilities),
                ('Break_Values', self.breakValues),
                ('Break_Units', self.measurementUnits),
                ('Service_Areas', self.outputServiceAreas),
                ('Travel_Direction', self.TRAVEL_DIR_KEYWORDS[self.travelDirection]),
                ('Polygons_for_Multiple_Facilities', self.MERGE_POLYGONS_KEYWORDS[self.polygonType]),
                ('Polygon_Overlap_Type', self.overlapType.upper()),
                ('Detailed_Polygons', self.detailedPolygons),
                ('Polygon_Trim_Distance', self.trimDistance),
                ('Polygon_Simplification_Tolerance', self.simplificationTolerance),
                ('UTurn_Policy', self.UTURN_KEYWORDS[self.uTurnAtJunctions]),
                ('Use_Hierarchy_in_Analysis', self.useHierarchy),
                ('Point_Barriers', self.pointBarriers),
                ('Line_Barriers', self.lineBarriers),
                ('Polygon_Barriers', self.polygonBarriers),
                ('Time_of_Day', self.timeOfDay),
                ('Time_Zone_for_Time_of_Day', self.TIME_ZONE_USAGE_KEYWORDS[self.timeZoneUsage]),
                ('Restrictions', self.restrictions),
                ('Attribute_Parameter_Values', self.attributeParameterValues),
                ('Travel_Mode', self.portalTravelMode),
                ('Save_Output_Network_Analysis_Layer', self.saveLayerFile),
                ('Overrides', self.overrides)
            ]
          
            #Fail if no facilities are given
            facility_count = int(arcpy.management.GetCount(self.facilities).getOutput(0))
            invalid_facility_count = 0
            if facility_count == 0:
                arcpy.AddIDMessage("ERROR", 30117)
                raise InputError
    
            #Determine the network dataset to use. If analysis region is specified use that as
            #the network dataset layer name
            self._selectNetworkDataset(self.facilities)
    
            #If using exact solve and generating detailed polygons, raise error if largest break value is greater
            #than 15 minutes/miles
            if self.useHierarchy == False and self.detailedPolygons and enforce_detailed_polys_limit:
                break_value_list = [val.encode("utf-8") for val in self.breakValues.strip().split()]
                #Check if all the break value are numeric
                try:
                    end_break_value = max([str_to_float(val) for val in break_value_list])
                except ValueError:
                    arcpy.AddIDMessage("ERROR", 30118)
                    raise InputError
                #Find the largest break value.
                if self.measurementUnits.lower() in self.TIME_UNITS:
                    impedance_unit = self.parser.get(self.templateNDS, "time_attribute_units")
                    is_impedance_time_based = True 
                else:
                    impedance_unit = self.parser.get(self.templateNDS, "distance_attribute_units")
                    is_impedance_time_based = False
                converted_break_value_list = nau.convert_units(break_value_list, self.measurementUnits, impedance_unit)
                convereted_end_break_value = max([str_to_float(val) for val in converted_break_value_list])
                if is_impedance_time_based:
                    if max_break_time_detailed_polys and (convereted_end_break_value > max_break_time_detailed_polys):
                        conv_max_break_time_detailed_polys = nau.convert_units(max_break_time_detailed_polys,
                                                                               impedance_unit, self.measurementUnits)
                        conv_max_break_time_detailed_polys_with_units = "{0} {1}".format(conv_max_break_time_detailed_polys,
                                                                                         self.measurementUnits)
                        arcpy.AddIDMessage("ERROR", 30136, end_break_value, conv_max_break_time_detailed_polys_with_units)
                        raise InputError
                else:
                    if max_break_distance_detailed_polys and (convereted_end_break_value > max_break_distance_detailed_polys):
                        conv_max_break_dist_detailed_polys = nau.convert_units(max_break_distance_detailed_polys,
                                                                               impedance_unit, self.measurementUnits)
                        conv_max_break_dist_detailed_polys_with_units = "{0} {1}".format(conv_max_break_dist_detailed_polys,
                                                                                         self.measurementUnits)
                        arcpy.AddIDMessage("ERROR", 30136, end_break_value,
                                           conv_max_break_dist_detailed_polys_with_units)
                        raise InputError     

            #check if we have a remote NDS
            if self.connectionFile:                   
                #Add remote tool
                self.logger.debug(u"Adding remote service {0} from {1}".format(self.serviceName, self.connectionFile))
                remote_tool_name, remote_toolbox = add_remote_toolbox(self.connectionFile, self.serviceName)

                #specify parameter values for the remote tool
                #need to pass boolean values for boolean parameters when calling the remote service
                task_params = [self.facilities, self.breakValues, self.measurementUnits, "#", self.travelDirection,
                               self.timeOfDay, self.useHierarchy, self.uTurnAtJunctions, self.polygonType,
                               self.overlapType, self.detailedPolygons, self.trimDistance,
                               self.simplificationTolerance, self.pointBarriers, self.lineBarriers,
                               self.polygonBarriers, "#", self.attributeParameterValues, self.timeZoneUsage,
                               self.portalTravelMode, self.impedance, self.saveLayerFile, self.overrides]
        
                #remove any unsupported restriction parameters
                if self.isCustomTravelMode:
                    remote_tool_param_info = arcpy.GetParameterInfo(remote_tool_name)
                    remote_tool_restriction_param = remote_tool_param_info[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX]
                    task_params[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX] = get_valid_restrictions_remote_tool(remote_tool_restriction_param,
                                                                                                                self.restrictions)
                #execute the remote tool
                self.toolResult = execute_remote_tool(remote_toolbox, remote_tool_name, task_params)
                #report errors and exit in case the remote tool failed.
                if self.toolResult.maxSeverity == 2:
                    self.solveSucceeded = False
                    error_messages = self.toolResult.getMessages(1) + self.toolResult.getMessages(2)
                    raise InputError(error_messages)
                else:
                    #Save the results
                    self.solveSucceeded = True
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(0), self.outputServiceAreas)
                    self.outputLayer = self.toolResult.getOutput(2)
        
            else:
                #Add the network dataset that we wish to use.    
                user_parameters.append(("Network_Dataset", self.outputNDS))
        
                #Get the time attribute, distance attribute and feature locator where clause from config file
                nds_property_values = self._getToolParametersFromNDSProperties()
        
                #Create a dict that contains all the tool parameters
                tool_parameters = dict(nds_property_values + constant_params + user_parameters)
                tool_parameters.update(service_limits)

                #Update time attribute and distance attribute when using custom travel mode. 
                if self.isCustomTravelMode:
                    tool_parameters["Time_Attribute"] = self.customTravelModeTimeAttribute
                    tool_parameters["Distance_Attribute"] = self.customTravelModeDistanceAttribute
 
                #Call the big button tool
                self._executeBigButtonTool(tool_parameters)
    
            #Fail if the count of features in output service areas exceeds the maximum number of records returned by 
            #the service
            self._checkMaxOutputFeatures(self.outputServiceAreas, 30144) 
    
            if self.logger.DEBUG:
                #print the execution time for the main tool
                self.logger.debug(u"{0} tool {1}".format(self.TOOL_NAME, self.toolResult.getMessage(self.toolResult.messageCount - 1)))
    
            if self.toolResult.maxSeverity == 1:
                messages = self.toolResult.getMessages(1).split("\n")
                INVALID_FACILITY_MESSAGE = 'in "Facilities" is unlocated'
                for msg in messages:
                    self.logger.warning(msg)
                    if msg.find(INVALID_FACILITY_MESSAGE) != -1:
                        invalid_facility_count += 1
            elif self.toolResult.maxSeverity == 0:
                if self.logger.DEBUG:
                    self.logger.info(self.toolResult.getMessages())
            else:
                #Tool failed. Add warning and error messages and raise exception
                self.logger.warning(self.toolResult.getMessages(1))
                self.logger.error(self.toolResult.getMessages(2))
                raise arcpy.ExecuteError

            #Get the layer file
            self.outputLayer = self.toolResult.getOutput(2)
    
            #Add metering and royalty messages
            #numObjects = number of valid facilities * number of breaks
            break_count = len(self.breakValues.strip().split())
            valid_facility_count = facility_count - invalid_facility_count
            num_objects = break_count * valid_facility_count
            arcpy.gp._arc_object.LogUsageMetering(5555, self.__class__.__name__, num_objects)
            arcpy.gp._arc_object.LogUsageMetering(9999, self.outputNDS, num_objects)
            self.solveSucceeded = True    

        except InputError as ex:
            self._handleInputErrorException(ex)
        except arcpy.ExecuteError:
            self._handleArcpyExecuteErrorException()
        except Exception as ex:
            self._handleException()

class SolveVehicleRoutingProblem(NetworkAnalysisService):
    '''SolveVehicleRoutingProblem geoprocessing service'''

    OUTPUT_STOPS_NAME = "Stops"
    OUTPUT_UNASSIGNED_STOPS_NAME = "UnassignedStops"
    OUTPUT_ROUTES_NAME = "Routes"
    OUTPUT_DIRECTIONS_NAME = "Directions"
    EXTENT_FIELDS = NetworkAnalysisService.EXTENT_FIELDS[:]
    EXTENT_FIELDS[2] = "GPVehicleRoutingProblemService"
    NDS_PROPERTY_NAMES = ("time_attribute", "distance_attribute", "feature_locator_where_clause")
    #MAX_FEATURES = 2000000
    REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX = 19
    TOOL_NAME = "SolveVehicleRoutingProblem_na"
    HELPER_SERVICES_KEY = "asyncVRP"

    def __init__(self, *args, **kwargs):
        '''constructor'''

        #Call the base class constructor to sets the common tool parameters as instance attributes
        super(SolveVehicleRoutingProblem, self).__init__(*args, **kwargs)

        #Store tool parameters as instance attributes
        self.orders = kwargs.get("Orders", None)
        self.depots = kwargs.get("Depots", None)
        self.routes = kwargs.get("Routes", None)
        self.breaks = kwargs.get("Breaks", None)
        self.timeUnits = kwargs.get("Time_Units", None)
        self.timeZoneUsageForTimeFields = kwargs.get("Time_Zone_Usage_for_Time_Fields", None)
        self.distanceUnits = kwargs.get("Distance_Units", None)
        self.timeWindowFactor = kwargs.get("Time_Window_Factor", None)
        self.spatiallyClusterRoutes = kwargs.get("Spatially_Cluster_Routes", None)
        self.routeZones = kwargs.get("Route_Zones", None)
        self.routeRenewals = kwargs.get("Route_Renewals", None)
        self.orderPairs = kwargs.get("Order_Pairs", None)
        self.excessTransitFactor = kwargs.get("Excess_Transit_Factor", None)
        self.populateRouteLines = kwargs.get("Populate_Route_Lines", None)
        self.routeLineSimplicationTolerance = kwargs.get("Route_Line_Simplification_Tolerance", None)
        #Set simplification tolerance to None if value is 0
        if str_to_float(self.routeLineSimplicationTolerance.split(" ")[0]) == 0:
            self.routeLineSimplicationTolerance = None
        self.populateDirections = kwargs.get("Populate_Directions", None)
        self.directionsLanguage = kwargs.get("Directions_Language", None)
        self.directionsStyleName = kwargs.get("Directions_Style_Name", None)
        self.saveRouteData = kwargs.get("Save_Route_Data", None)

        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))
        
        
        #derived outputs
        self.outputUnassignedStops = os.path.join(self.outputGeodatabase, self.OUTPUT_UNASSIGNED_STOPS_NAME)
        self.outputStops = os.path.join(self.outputGeodatabase, self.OUTPUT_STOPS_NAME)
        self.outputRoutes = os.path.join(self.outputGeodatabase, self.OUTPUT_ROUTES_NAME)
        self.outputDirections = os.path.join(self.outputGeodatabase, self.OUTPUT_DIRECTIONS_NAME)
        self.outputRouteData = ""
        
    def execute(self):
        '''Main execution logic'''

        try:
            arcpy.CheckOutExtension("network")

            #Get the properties for all network datasets from a propeties file. 
            self._getNetworkDatasetProperties()

            #Select the travel mode
            self._selectTravelMode()

            #Get the values for big button tool parameters that are used as constraints
            service_limits = self._getServiceCapabilities()
            self.logger.debug("Service Limits: {0}".format(service_limits))

            #Define values for big button tool parameters that are not specified from the service
            constant_params = [
                ('output_workspace_location', "#"),
                ('output_unassigned_stops_name', self.OUTPUT_UNASSIGNED_STOPS_NAME),
                ('output_stops_name', self.OUTPUT_STOPS_NAME),
                ('output_routes_name', self.OUTPUT_ROUTES_NAME),
                ('output_directions_name', self.OUTPUT_DIRECTIONS_NAME),
                ('maximum_snap_tolerance', "20 Kilometers"),
                ('exclude_restricted_portions_of_the_network', "EXCLUDE"),
                ('ignore_network_location_fields', "IGNORE"),
            ]

            #Create a list of user defined parameter names and their values
            user_parameters = [
                ('orders', self.orders),
                ('depots', self.depots),
                ('routes', self.routes),
                ('breaks', self.breaks),
                ('time_units', self.timeUnits),
                ('distance_units', self.distanceUnits),
                ('default_date', self.timeOfDay),
                ('uturn_policy', self.uTurnAtJunctions),
                ('time_window_factor', self.timeWindowFactor),
                ('spatially_cluster_routes', self.spatiallyClusterRoutes),
                ('route_zones', self.routeZones),
                ('route_renewals', self.routeRenewals),
                ('order_pairs', self.orderPairs),
                ('excess_transit_factor', self.excessTransitFactor),
                ('point_barriers', self.pointBarriers),
                ('line_barriers', self.lineBarriers),
                ('polygon_barriers', self.polygonBarriers),
                ('use_hierarchy_in_analysis', self.useHierarchy),
                ('restrictions', self.restrictions),
                ('attribute_parameter_values', self.attributeParameterValues),
                ('travel_mode', self.portalTravelMode),
                ('populate_route_lines', self.populateRouteLines),
                ('route_line_simplification_tolerance', self.routeLineSimplicationTolerance),
                ('populate_directions', self.populateDirections),
                ('directions_language', self.directionsLanguage),
                ('directions_style_name', self.directionsStyleName),
                ('time_zone_usage_for_time_fields', self.timeZoneUsageForTimeFields),
                ('save_output_layer', self.saveLayerFile),
                ('overrides', self.overrides),
                ('save_route_data', self.saveRouteData),
                ('service_capabilities', service_limits),                 
            ]

          
            #Fail if no orders are given
            order_count = int(arcpy.management.GetCount(self.orders).getOutput(0))
            if order_count == 0:
                arcpy.AddIDMessage("ERROR", 30138)
                raise InputError

            #Determine the network dataset to use. If analysis region is specified use that as
            #the network dataset layer name
            self._selectNetworkDataset(self.orders, self.depots)

            if self.connectionFile:
                #Add remote tool
                self.logger.debug(u"Adding remote service {0} from {1}".format(self.serviceName, self.connectionFile))
                remote_tool_name, remote_toolbox = add_remote_toolbox(self.connectionFile, self.serviceName)

                #specify parameter values for the remote tool
                #need to pass boolean values for boolean parameters when calling the remote service
                task_params = [self.orders, self.depots, self.routes, self.breaks, self.timeUnits, self.distanceUnits,
                               "#", self.timeOfDay, self.uTurnAtJunctions, self.timeWindowFactor,
                               self.spatiallyClusterRoutes, self.routeZones, self.routeRenewals, self.orderPairs,
                               self.excessTransitFactor, self.pointBarriers, self.lineBarriers, self.polygonBarriers,
                               self.useHierarchy, "#", self.attributeParameterValues, self.populateRouteLines,
                               self.routeLineSimplicationTolerance, self.populateDirections, self.directionsLanguage,
                               self.directionsStyleName, self.portalTravelMode, self.impedance,
                               self.timeZoneUsageForTimeFields, self.saveLayerFile, self.overrides, self.saveRouteData]
                #remove any unsupported restriction parameters
                if self.isCustomTravelMode:
                    remote_tool_param_info = arcpy.GetParameterInfo(remote_tool_name)
                    remote_tool_restriction_param = remote_tool_param_info[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX]
                    task_params[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX] = get_valid_restrictions_remote_tool(remote_tool_restriction_param, 
                                                                                                                self.restrictions)
                #execute the remote tool
                self.toolResult = execute_remote_tool(remote_toolbox, remote_tool_name, task_params)
                result_severity =  self.toolResult.maxSeverity
                if result_severity == -1:
                    result_severity = arcpy.GetMaxSeverity()
                #SolveVRP tool always produces some result even in case of failure
                if result_severity != 2:
                    #Save the results
                    solve_status = self.toolResult.getOutput(4)
                    if solve_status.lower() == 'true':
                        self.solveSucceeded = True
                    arcpy.management.CopyRows(self.toolResult.getOutput(0), self.outputUnassignedStops)
                    arcpy.management.CopyRows(self.toolResult.getOutput(1), self.outputStops)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(2), self.outputRoutes)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(3), self.outputDirections)
                    self.outputLayer = self.toolResult.getOutput(5)
                    self.outputRouteData = self.toolResult.getOutput(6)
            else:
        
                #Add the network dataset that we wish to use.   
                user_parameters.append(("network_dataset", self.outputNDS))
        
                #Get the time attribute, distance attribute and feature locator where clause from config file
                nds_property_values = self._getToolParametersFromNDSProperties()
        
                #Create a dict that contains all the tool parameters and call the tool.
                tool_parameters = dict(nds_property_values + constant_params + user_parameters)
                #Update time attribute and distance attribute when using custom travel mode. 
                if self.isCustomTravelMode:
                    tool_parameters["time_attribute"] = self.customTravelModeTimeAttribute
                    tool_parameters["distance_attribute"] = self.customTravelModeDistanceAttribute

                #Check if inputs are within the max walking extent if perform walk type analysis
                self._checkWalkingExtent(self.orders, self.depots)

                #Call the big button tool
                self._executeBigButtonTool(tool_parameters)
                #get outputs from the result
                solve_status = self.toolResult.getOutput(0)
                if solve_status.lower() == 'true':
                    self.solveSucceeded = True
                self.outputUnassignedStops = self.toolResult.getOutput(1)
                self.outputStops = self.toolResult.getOutput(2)
                self.outputRoutes = self.toolResult.getOutput(3)
                self.outputDirections = self.toolResult.getOutput(4)
                self.outputLayer = self.toolResult.getOutput(5)
                self.outputRouteData = self.toolResult.getOutput(6)
    
            #Fail if the count of features in directions exceeds the maximum number of records
            #returned by the service
            if self.populateDirections:
                self._checkMaxOutputFeatures(self.outputDirections)
                #generalize directions features
                arcpy.edit.Generalize(self.outputDirections, self.routeLineSimplicationTolerance)
            
            #Log messages from execution of remote tool or big button tool
            self._logToolExecutionMessages()   
            
            #Add metering and royalty messages
            #numObjects = number of routes with orders           
            num_objects = 0
            with arcpy.da.SearchCursor(self.outputRoutes, "OrderCount", "OrderCount IS NOT NULL") as cursor:
                for row in cursor:
                    num_objects += 1   
            if num_objects:
                arcpy.gp._arc_object.LogUsageMetering(5555, self.__class__.__name__, num_objects)
                arcpy.gp._arc_object.LogUsageMetering(9999, self.outputNDS, num_objects) 

        except InputError as ex:
            self._handleInputErrorException(ex)
        except arcpy.ExecuteError:
            self._handleArcpyExecuteErrorException()
        except Exception as ex:
            self._handleException()

        return

class EditVehicleRoutingProblem(SolveVehicleRoutingProblem):
    '''EditVehicleRoutingProblem geoprocessing service'''

    #Overwrites from base class
    EXTENT_FIELDS = NetworkAnalysisService.EXTENT_FIELDS[:]
    EXTENT_FIELDS[2] = "GPVehicleRoutingProblemSyncService"
    #MAX_FEATURES = 10000
    HELPER_SERVICES_KEY = "syncVRP"

class SolveLocationAllocation(NetworkAnalysisService):
    '''SolveLocationAllocation geoprocessing service'''

    OUTPUT_ALLOCATION_LINES_NAME = "AllocationLines"
    OUTPUT_DEMAND_POINTS_NAME = "DemandPoints"
    OUTPUT_FACILITIES_NAME = "Facilities"
    OUTPUT_ROUTE_EDGES_NAME = "RouteEdges"
    TRAVEL_DIR_KEYWORDS = {
        "Facility to Demand" : "FACILITY_TO_DEMAND",
        "Demand to Facility" : "DEMAND_TO_FACILITY"
    }
    PROBLEM_TYPE_KEYWORDS = {
        "Maximize Attendance": "MAXIMIZE_ATTENDANCE",
        "Maximize Capacitated Coverage": "MAXIMIZE_CAPACITATED_COVERAGE",
        "Maximize Coverage" : "MAXIMIZE_COVERAGE",
        "Maximize Market Share" : "MAXIMIZE_MARKET_SHARE",
        "Minimize Facilities" : "MINIMIZE_FACILITIES",
        "Minimize Impedance" : "MINIMIZE_IMPEDANCE",
        "Target Market Share" : "TARGET_MARKET_SHARE"
    }
    EXTENT_FIELDS = NetworkAnalysisService.EXTENT_FIELDS[:]
    EXTENT_FIELDS[2] = "GPLocationAllocationService"
    #MAX_FEATURES = 1000000
    REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX = 19
    
    TOOL_NAME = "SolveLocationAllocation_na"
    HELPER_SERVICES_KEY = "asyncLocationAllocation"

    def __init__(self, *args, **kwargs):
        '''Constructor'''

        #Call the base class constructor to sets the common tool parameters as instance attributes
        super(SolveLocationAllocation, self).__init__(*args, **kwargs)

        #Store tool parameters as instance attributes
        self.facilities = kwargs.get("Facilities", None)
        self.demandPoints = kwargs.get("Demand_Points", None)
        self.problemType = kwargs.get("Problem_Type", None)
        self.facilitiesToFind = kwargs.get("Number_of_Facilities_to_Find", None)
        
        self.deafultMeasurementCutoff = kwargs.get("Default_Measurement_Cutoff", None)
        if self.deafultMeasurementCutoff:
            try:
                self.deafultMeasurementCutoff = str_to_float(self.deafultMeasurementCutoff)
            except ValueError as ex:
                self.deafultMeasurementCutoff = None

        self.defaultCapacity = kwargs.get("Default_Capacity", None)
        self.targetMarketShare = kwargs.get("Target_Market_Share", None)
        self.travelDirection = kwargs.get("Travel_Direction", None)
        self.measurementTransformationModel = kwargs.get("Measurement_Transformation_Model", None)
        self.measurementTransformationFactor = kwargs.get("Measurement_Transformation_Factor", None)
        self.allocationLineShape = kwargs.get("Allocation_Line_Shape", None)
  
        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))
        
        #derived outputs
        self.outputAllocationLines = os.path.join(self.outputGeodatabase, self.OUTPUT_ALLOCATION_LINES_NAME)
        self.outputDemandPoints = os.path.join(self.outputGeodatabase, self.OUTPUT_DEMAND_POINTS_NAME)
        self.outputFacilities = os.path.join(self.outputGeodatabase, self.OUTPUT_FACILITIES_NAME)

    def execute(self):
        '''Main execution logic'''
        try:
            arcpy.CheckOutExtension("network")

            #Get the properties for all network datasets from a propeties file. 
            self._getNetworkDatasetProperties()

            #Select the travel mode
            self._selectTravelMode()

            #Get the values for big button tool parameters that are used as constraints
            service_limits = self._getServiceCapabilities()
            self.logger.debug("Service Limits: {0}".format(service_limits))

            #Define values for big button tool parameters that are not specified from the service
            constant_params = [('Maximum_Snap_Tolerance', '20 Kilometers'),
                               ('Accumulate_Attributes', []),
                               ('Output_Geodatabase', self.outputGeodatabase),
                               ('Output_Allocation_Lines_Name', self.OUTPUT_ALLOCATION_LINES_NAME),
                               ('Output_Demand_Points_Name', self.OUTPUT_DEMAND_POINTS_NAME),
                               ('Output_Facilities_Name', self.OUTPUT_FACILITIES_NAME),
                               ('Output_Route_Edges_Name', self.OUTPUT_ROUTE_EDGES_NAME),
                               ]

            #Create a list of user defined parameter names and their values
            user_parameters = [('Facilities', self.facilities),
                               ('Demand_Points', self.demandPoints),
                               ('Measurement_Units', self.measurementUnits),
                               ('Problem_Type', self.PROBLEM_TYPE_KEYWORDS[self.problemType]),
                               ('Number_of_Facilities_to_Find', self.facilitiesToFind),
                               ('Default_Measurement_Cutoff', self.deafultMeasurementCutoff),
                               ('Default_Capacity', self.defaultCapacity),
                               ('Target_Market_Share', self.targetMarketShare),
                               ('Measurement_Transformation_Model', self.measurementTransformationModel),
                               ('Measurement_Transformation_Factor', self.measurementTransformationFactor),
                               ('Travel_Direction', self.TRAVEL_DIR_KEYWORDS[self.travelDirection]),
                               ('Time_of_Day', self.timeOfDay),
                               ('Time_Zone_for_Time_of_Day', self.TIME_ZONE_USAGE_KEYWORDS[self.timeZoneUsage]),
                               ('UTurn_Policy', self.UTURN_KEYWORDS[self.uTurnAtJunctions]),
                               ('Allocation_Line_Shape', self.ROUTE_SHAPE_KEYWORDS[self.allocationLineShape]),
                               ('Point_Barriers', self.pointBarriers),
                               ('Line_Barriers', self.lineBarriers),
                               ('Polygon_Barriers', self.polygonBarriers),
                               ('Use_Hierarchy_in_Analysis', self.useHierarchy),
                               ('Restrictions', self.restrictions),
                               ('Attribute_Parameter_Values', self.attributeParameterValues),
                               ('Travel_Mode', self.portalTravelMode),
                               ('Save_Output_Network_Analysis_Layer', self.saveLayerFile),
                               ('Overrides', self.overrides),
                               ]
   
            #Fail if no facilities or demand points are given
            demand_point_count = int(arcpy.management.GetCount(self.demandPoints).getOutput(0))
            facility_count = int(arcpy.management.GetCount(self.facilities).getOutput(0))
            if demand_point_count == 0 or facility_count == 0:
                arcpy.AddIDMessage("ERROR", 30139)
                raise InputError

            #Determine the network dataset to use. If analysis region is specified use that as
            #the network dataset layer name
            self._selectNetworkDataset(self.demandPoints, self.facilities)

            if self.connectionFile:
                #Add remote tool
                self.logger.debug(u"Adding remote service {0} from {1}".format(self.serviceName, self.connectionFile))
                remote_tool_name, remote_toolbox = add_remote_toolbox(self.connectionFile, self.serviceName)

                #specify parameter values for the remote tool
                #need to pass boolean values for boolean parameters when calling the remote service
                task_params = [self.facilities, self.demandPoints, self.measurementUnits, "#", self.problemType,
                               self.facilitiesToFind, self.deafultMeasurementCutoff, self.defaultCapacity,
                               self.targetMarketShare, self.measurementTransformationModel,
                               self.measurementTransformationFactor, self.travelDirection, self.timeOfDay,
                               self.timeZoneUsage, self.uTurnAtJunctions, self.pointBarriers, self.lineBarriers,
                               self.polygonBarriers, self.useHierarchy, "#", self.attributeParameterValues, 
                               self.allocationLineShape, self.portalTravelMode, self.impedance, self.saveLayerFile,
                               self.overrides]

                #remove any unsupported restriction parameters when using a custom travel mode
                if self.isCustomTravelMode:
                    remote_tool_param_info = arcpy.GetParameterInfo(remote_tool_name)
                    remote_tool_restriction_param = remote_tool_param_info[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX]
                    task_params[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX] = get_valid_restrictions_remote_tool(remote_tool_restriction_param,
                                                                                                                self.restrictions)
                #execute the remote tool
                self.toolResult = execute_remote_tool(remote_toolbox, remote_tool_name, task_params)

                #report errors and exit in case the remote tool failed.
                if self.toolResult.maxSeverity == 2:
                    error_messages = self.toolResult.getMessages(1) + self.toolResult.getMessages(2)
                    raise InputError(error_messages)
                else:
                    #Save the results
                    solve_status = self.toolResult.getOutput(0)
                    if solve_status.lower() == 'true':
                        self.solveSucceeded = True
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(1), self.outputAllocationLines)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(2), self.outputFacilities)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(3), self.outputDemandPoints)
                    self.outputLayer = self.toolResult.getOutput(4)
            
            else:
        
                #Add the network dataset that we wish to use.    
                user_parameters.append(("Network_Dataset", self.outputNDS))
        
                #Get the time attribute, distance attribute and feature locator where clause from config file
                nds_property_values = self._getToolParametersFromNDSProperties()
        
                #Create a dict that contains all the tool parameters and call the tool.
                tool_parameters = dict(nds_property_values + constant_params + user_parameters)
                tool_parameters.update(service_limits)
                if self.isCustomTravelMode:
                    tool_parameters["Time_Attribute"] = self.customTravelModeTimeAttribute
                    tool_parameters["Distance_Attribute"] = self.customTravelModeDistanceAttribute

                #Update time attribute and distance attribute when using custom travel mode. 
                self._checkWalkingExtent(self.demandPoints, self.facilities)

                #Call the big button tool
                self._executeBigButtonTool(tool_parameters)
                
                #get outputs from the result
                solve_status = self.toolResult.getOutput(0)
                if solve_status.lower() == 'true':
                    self.solveSucceeded = True
                self.outputAllocationLines = self.toolResult.getOutput(1)
                self.outputFacilities = self.toolResult.getOutput(2)
                self.outputDemandPoints = self.toolResult.getOutput(3)
                self.outputLayer = self.toolResult.getOutput(5)
                    
            #Log messages from execution of remote or big button tool
            self._logToolExecutionMessages()
            
            #Fail if the count of features in output demand points exceeds the maximum number of records returned by 
            #the service
            self._checkMaxOutputFeatures(self.outputDemandPoints, 30170) 

            #Add metering and royalty messages
            #numObjects = number of allocated demand points
            output_demand_points_layer = "OutputDemandPointsLayer"
            allocated_demand_points_where_clause = "FacilityOID IS NOT NULL"
            arcpy.management.MakeFeatureLayer(self.outputDemandPoints, output_demand_points_layer,
                                              allocated_demand_points_where_clause)
            num_objects = int(arcpy.management.GetCount(output_demand_points_layer).getOutput(0))                   
            if num_objects:
                arcpy.gp._arc_object.LogUsageMetering(5555, self.__class__.__name__, num_objects)
                arcpy.gp._arc_object.LogUsageMetering(9999, self.outputNDS, num_objects)

        except InputError as ex:
            self._handleInputErrorException(ex)
        except arcpy.ExecuteError:
            self._handleArcpyExecuteErrorException()
        except Exception as ex:
            self._handleException()

        return

class GenerateOriginDestinationCostMatrix(NetworkAnalysisService):
    '''GenerateOriginDestinationCostMatrix geoprocessing service'''

    OUTPUT_OD_LINES_NAME = "ODLines"
    OUTPUT_ORIGINS_NAME = "Origins"
    OUTPUT_DESTINATIONS_NAME = "Destinations"
    EXTENT_FIELDS = NetworkAnalysisService.EXTENT_FIELDS[:]
    EXTENT_FIELDS[2] = "GPOriginDestinationCostMatrixService"
    REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX = 15
    
    TOOL_NAME = "GenerateOriginDestinationCostMatrix_na"
    HELPER_SERVICES_KEY = "asyncODCostMatrix"

    def __init__(self, *args, **kwargs):
        '''constructor'''

        #Call the base class constructor to sets the common tool parameters as instance attributes
        super(GenerateOriginDestinationCostMatrix, self).__init__(*args, **kwargs)

        #Store tool parameters as instance attributes
        self.origins = kwargs.get("Origins", None)
        self.destinations = kwargs.get("Destinations", None)
        self.timeUnits = kwargs.get("Time_Units", None)
        self.distanceUnits = kwargs.get("Distance_Units", None)
        self.destinationsToFind = kwargs.get("Number_of_Destinations_to_Find", None)
        self.cutoff = kwargs.get("Cutoff", None)
        if self.cutoff:
            try:
                self.cutoff = locale.atof(self.cutoff)
            except ValueError as ex:
                self.cutoff = None
        self.odLineShape = kwargs.get("Origin_Destination_Line_Shape", None)

        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))

        #derived outputs
        self.outputGeodatabase = arcpy.env.scratchGDB
        self.outputODLines = os.path.join(self.outputGeodatabase, self.OUTPUT_OD_LINES_NAME)
        self.outputOrigins = os.path.join(self.outputGeodatabase, self.OUTPUT_ORIGINS_NAME)
        self.outputDestinations = os.path.join(self.outputGeodatabase, self.OUTPUT_DESTINATIONS_NAME)

    def execute(self):
        '''Main execution logic'''
        try:
            arcpy.CheckOutExtension("network")

            #Get the properties for all network datasets from a propeties file. 
            self._getNetworkDatasetProperties()

            #Select the travel mode
            self._selectTravelMode()

            #Get the values for big button tool parameters that are used as constraints
            service_limits = self._getServiceCapabilities()
            self.logger.debug("Service Limits: {0}".format(service_limits))

            #Define values for big button tool parameters that are not specified from the service
            constant_params = [('Maximum_Snap_Tolerance', '20 Kilometers'),
                               ('Accumulate_Attributes', []),
                               ('Output_Geodatabase', self.outputGeodatabase),
                               ('Output_Origin_Destination_Lines_Name', self.OUTPUT_OD_LINES_NAME),
                               ('Output_Origins_Name', self.OUTPUT_ORIGINS_NAME),
                               ('Output_Destinations_Name', self.OUTPUT_DESTINATIONS_NAME),
                               ]

            #Create a list of user defined parameter names and their values
            user_parameters = [('Origins', self.origins),
                               ('Destinations', self.destinations),
                               ('Travel_Mode', self.portalTravelMode),
                               ('Time_Units', self.timeUnits),
                               ('Distance_Units', self.distanceUnits),
                               ('Number_of_Destinations_to_Find', self.destinationsToFind),
                               ('Cutoff', self.cutoff),
                               ('Time_of_Day', self.timeOfDay),
                               ('Time_Zone_for_Time_of_Day', self.TIME_ZONE_USAGE_KEYWORDS[self.timeZoneUsage]),
                               ('UTurn_Policy', self.UTURN_KEYWORDS[self.uTurnAtJunctions]),
                               ('Origin_Destination_Line_Shape', self.ROUTE_SHAPE_KEYWORDS[self.odLineShape]),
                               ('Point_Barriers', self.pointBarriers),
                               ('Line_Barriers', self.lineBarriers),
                               ('Polygon_Barriers', self.polygonBarriers),
                               ('Use_Hierarchy_in_Analysis', self.useHierarchy),
                               ('Restrictions', self.restrictions),
                               ('Attribute_Parameter_Values', self.attributeParameterValues),
                               ('Save_Output_Network_Analysis_Layer', self.saveLayerFile),
                               ('Overrides', self.overrides),
                               ]
   
            #Fail if no origins or destinations are given
            origin_count = int(arcpy.management.GetCount(self.origins).getOutput(0))
            destination_count = int(arcpy.management.GetCount(self.destinations).getOutput(0))
            if origin_count == 0 or destination_count == 0:
                arcpy.AddIDMessage("ERROR", 30168)
                raise InputError

            #Determine the network dataset to use. If analysis region is specified use that as
            #the network dataset layer name
            self._selectNetworkDataset(self.origins, self.destinations)

            if self.connectionFile:
                #Add remote tool
                self.logger.debug(u"Adding remote service {0} from {1}".format(self.serviceName, self.connectionFile))
                remote_tool_name, remote_toolbox = add_remote_toolbox(self.connectionFile, self.serviceName)

                #specify parameter values for the remote tool
                #need to pass boolean values for boolean parameters when calling the remote service
                task_params = [self.origins, self.destinations, self.portalTravelMode, self.timeUnits,
                               self.distanceUnits, "#", self.destinationsToFind, self.cutoff, self.timeOfDay,
                               self.timeZoneUsage, self.pointBarriers, self.lineBarriers, self.polygonBarriers,
                               self.uTurnAtJunctions, self.useHierarchy, "#", self.attributeParameterValues, 
                               self.impedance, self.odLineShape, self.saveLayerFile, self.overrides]

                #remove any unsupported restriction parameters when using a custom travel mode
                if self.isCustomTravelMode:
                    remote_tool_param_info = arcpy.GetParameterInfo(remote_tool_name)
                    remote_tool_restriction_param = remote_tool_param_info[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX]
                    task_params[self.REMOTE_TOOL_RESTRICTIONS_PARAM_INDEX] = get_valid_restrictions_remote_tool(remote_tool_restriction_param,
                                                                                                                self.restrictions)
                #execute the remote tool
                self.toolResult = execute_remote_tool(remote_toolbox, remote_tool_name, task_params)

                #report errors and exit in case the remote tool failed.
                if self.toolResult.maxSeverity == 2:
                    error_messages = self.toolResult.getMessages(1) + self.toolResult.getMessages(2)
                    raise InputError(error_messages)
                else:
                    #Save the results
                    solve_status = self.toolResult.getOutput(0)
                    if solve_status.lower() == 'true':
                        self.solveSucceeded = True
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(1), self.outputODLines)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(2), self.outputOrigins)
                    arcpy.management.CopyFeatures(self.toolResult.getOutput(3), self.outputDestinations)
                    self.outputLayer = self.toolResult.getOutput(4)
            
            else:
        
                #Add the network dataset that we wish to use.    
                user_parameters.append(("Network_Dataset", self.outputNDS))
        
                #Get the time attribute, distance attribute and feature locator where clause from config file
                nds_property_values = self._getToolParametersFromNDSProperties()
        
                #Create a dict that contains all the tool parameters and call the tool.
                tool_parameters = dict(nds_property_values + constant_params + user_parameters)
                tool_parameters.update(service_limits)
                #Update time attribute and distance attribute when using custom travel mode.
                if self.isCustomTravelMode:
                    tool_parameters["Time_Attribute"] = self.customTravelModeTimeAttribute
                    tool_parameters["Distance_Attribute"] = self.customTravelModeDistanceAttribute
                    tool_parameters["Impedance_Attribute"] = self.customTravelModeImpedanceAttribute

                #enforce walking travel mode extent constraint
                self._checkWalkingExtent(self.origins, self.destinations)

                #Call the big button tool
                self._executeBigButtonTool(tool_parameters)
                
                #get outputs from the result
                solve_status = self.toolResult.getOutput(0)
                if solve_status.lower() == 'true':
                    self.solveSucceeded = True
                self.outputODLines = self.toolResult.getOutput(1)
                self.outputOrigins = self.toolResult.getOutput(2)
                self.outputDestinations = self.toolResult.getOutput(3)
                self.outputLayer = self.toolResult.getOutput(4)
                    
            #Log messages from execution of remote or big button tool
            self._logToolExecutionMessages()
            
            #Fail if the count of features in output od lines exceeds the maximum number of records returned by 
            #the service
            self._checkMaxOutputFeatures(self.outputODLines, 30171) 

            #Add metering and royalty messages
            #numObjects = number of origins located on network * number of destinations located on network
            #Get the counts of unlocated origins from excluded origins 
            output_origins_layer = "OutputOriginsLayer"
            unlocated_where_clause = "Status NOT IN (0,5)"
            arcpy.management.MakeFeatureLayer(self.outputOrigins, output_origins_layer, unlocated_where_clause)
            unlocated_origin_count = int(arcpy.management.GetCount(output_origins_layer).getOutput(0))
            #Get the counts of unlocated destinations from excluded destinations
            output_destinations_layer = "OutputDestinationsLayer"
            arcpy.management.MakeFeatureLayer(self.outputDestinations, output_destinations_layer, 
                                              unlocated_where_clause)
            unlocated_destination_count = int(arcpy.management.GetCount(output_destinations_layer).getOutput(0))

            #Calculate numObjects 
            num_objects = (origin_count - unlocated_origin_count) * (destination_count - unlocated_destination_count)
            
            #Get usage parameters to report
            odlines_count = int(arcpy.management.GetCount(self.outputODLines).getOutput(0))
            origins_extent = arcpy.Describe(self.origins).extent
            destinations_extent = arcpy.Describe(self.destinations).extent            
            if num_objects:
                task_name = self.__class__.__name__
                usage_metrics = {
                    "originCount" : origin_count,
                    "originExtent" : json.loads(origins_extent.JSON),
                    "destinationCount" : destination_count,
                    "destinationExtent" : json.loads(destinations_extent.JSON),
                    "destinationsToFind" : self.destinationsToFind,
                    "cutoff" : self.cutoff,
                    "odLinesCount" : odlines_count,
                }
                arcpy.gp._arc_object.LogUsageMetering(5555, task_name , num_objects)
                arcpy.gp._arc_object.LogUsageMetering(9999, self.outputNDS, num_objects)
                arcpy.gp._arc_object.LogUsageMetering(7777, task_name + json.dumps(usage_metrics), num_objects)

        except InputError as ex:
            self._handleInputErrorException(ex)
        except arcpy.ExecuteError:
            self._handleArcpyExecuteErrorException()
        except Exception as ex:
            self._handleException()

        return

class Utilities(object):
    '''Utilities geprocessing service'''

    def __init__(self):
        '''Constructor'''

        #initialize instance names common to all child classes
        self.logger = Logger(LOG_LEVEL)

    def _handleExceptionError(self, ex):
        '''Handler for the generic exception'''
        if self.logger.DEBUG:
            #Get a nicely formatted traceback object except the first line.
            msgs = traceback.format_exception(*sys.exc_info())[1:]
            msgs[0] = "A geoprocessing error occurred in " + msgs[0].lstrip()
            for msg in msgs:
                self.logger.error(msg.strip())
        else:
            self.logger.error("A geoprocessing error occurred.")

class GetTravelModes(Utilities):
    '''GetTravelModes tool in the Utilities geoprocessing service'''

    FILE_TYPES = ["Default Localized Travel Modes File", "Default Travel Modes File"]

    def __init__(self, *args, **kwargs):
        '''Constructor'''

        #Call the base class constructor
        super(GetTravelModes, self).__init__()

        #Store tool parameters as instance attributes
        self.supportingFiles = kwargs.get("supportingFiles", None)
        #Get the supporting files as a dict of file_type and file path
        if self.supportingFiles:
            self.supportingFiles = {file_type : file_path.value for file_path, file_type in self.supportingFiles}
        else:
            self.logger.error("Value for supportingFiles is required")
            raise InputError

        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))
            self.logger.debug(u"Supporting files: {0}".format(self.supportingFiles))

        #derived outputs
        self.defaultTravelMode = u""
        self.outputTableName = u"supportedTravelModes"
        self.outputGeodatabase = "in_memory"
        self.outputTable = os.path.join(self.outputGeodatabase, self.outputTableName)

    def _createOutputTable(self, travel_modes_json, alt_travel_mode_names=None):
        '''Store the supported travel modes in a geodatabase table'''

        if alt_travel_mode_names is None:
            alt_travel_mode_names = {}

        #Create an empty output table with appropriate fields
        arcpy.management.CreateTable(self.outputGeodatabase, self.outputTableName)
        travel_mode_field_name = "TravelMode"
        travel_mode_name_field_name = "Name"
        travel_mode_name_alt_field_name = "AltName"
        travel_mode_id_field_name = "TravelModeId"
        arcpy.management.AddField(self.outputTable, travel_mode_name_field_name, "TEXT", field_length=255,
                                  field_alias="Travel Mode Name")
        arcpy.management.AddField(self.outputTable, travel_mode_id_field_name, "TEXT", field_length=50,
                                  field_alias="Travel Mode Identifier")
        arcpy.management.AddField(self.outputTable, travel_mode_field_name, "TEXT", field_length=65536,
                                  field_alias="Travel Mode Settings")
        arcpy.management.AddField(self.outputTable, travel_mode_name_alt_field_name, "TEXT", field_length=255,
                                  field_alias="Alternate Travel Mode Name")
        output_table_fields = (travel_mode_name_field_name, travel_mode_id_field_name, travel_mode_field_name,
                               travel_mode_name_alt_field_name)
        #Write supported travel modes to the output table
        with arcpy.da.InsertCursor(self.outputTable, output_table_fields) as cursor:
            for id in travel_modes_json:
                travel_mode = travel_modes_json[id]
                travel_mode_name = travel_mode["name"]
                cursor.insertRow((travel_mode_name,
                                  id,
                                  json.dumps(travel_mode),
                                  alt_travel_mode_names.get(id, travel_mode_name)
                                  ))

    def execute(self):
        '''Main execution logic'''
        try:
            #Determine the file types that have been specified as supporting files
            default_localized_travel_modes_file = self.supportingFiles.get(self.FILE_TYPES[0], None)
            default_travel_modes_file = self.supportingFiles.get(self.FILE_TYPES[1], None)
            
            #declare names used in this method
            org_id = ""
            culture = "en"
            nds_travel_modes = {}
            alt_travel_mode_names = {}
            travel_modes_all_lang = {}

            #Read the travel modes from the NDS
            if default_travel_modes_file and os.path.exists(default_travel_modes_file):
                with open(default_travel_modes_file, "r") as tm_fp:
                    file_json = json.load(tm_fp)
                    self.defaultTravelMode = file_json.get("defaultTravelMode", "")
                    nds_travel_modes = {nds_tm["id"] : nds_tm for nds_tm in file_json.get("supportedTravelModes", [])}     
            else:
                self.logger.error(u"A value for {0} file type must be specified".format(self.FILE_TYPES[1]))
                raise InputError

            #Get the owning system URL for the server hosting the service
            rest_info = get_rest_info()
            #A server that is not federated with a portal will not have owning system url. Return network dataset
            #travel modes if a server is not federated.
            if not "owningSystemUrl" in rest_info:
                self._createOutputTable(nds_travel_modes)
                return
        
            #Return org specific travel modes
            owning_system_url = rest_info["owningSystemUrl"]
            #Make sure the owning system URL is using https
            if not owning_system_url.startswith("https"):
                owning_system_url = owning_system_url.replace("http", "https")
            
            #Get the portal self
            hgp = init_hostedgp()
            portal_self_response = get_portal_self(hgp)

            if "id" in portal_self_response:
                #OAuth and non-OAuth based user logins should have id property in portal self response
                org_id = portal_self_response.get("id", "")
                #Get the language defined for the user
                if "user" in portal_self_response:
                    culture = portal_self_response["user"].get("culture","en")
                    #Some users in orgs can have null cultures. Use the culture defined for the org in such cases.
                    if not culture:
                        culture = portal_self_response.get("culture", "en")

            elif "appInfo" in portal_self_response:
                #This block should be executed only when app logins are used
                app_info = portal_self_response["appInfo"] 
                org_id = app_info.get("orgId", "")
                #If appInfo does not have a culture, use default en culture
                culture = app_info.get("culture", "en")

            #If for some reason we get a null culture, use en
            if not culture:
                culture = "en" 
            if not org_id:
                self.logger.error("Failed to get organization ID")
                raise arcpy.ExecuteError

            #Get the default travel mode from asyncRoute service
            helper_services = portal_self_response["helperServices"]
            if "asyncRoute" in helper_services:
                async_route = helper_services["asyncRoute"]
                if "defaultTravelMode" in async_route:
                    self.defaultTravelMode = async_route.get("defaultTravelMode", self.defaultTravelMode)

            #Get all the travel mode keys defined for the org
            #Get a file resource with key travelmodes.json. If the resource exists return all travel modes from the resource
            #Otherwise return default travel modes.
            try:
                org_travel_modes_file = os.path.join(arcpy.env.scratchFolder, "travelmodes.json")
                hgp.GetResourceAsFile("travelmodes.json", org_travel_modes_file)
                with open(org_travel_modes_file, "rb") as org_tm_fp:
                    travel_modes_resource_response = json.load(org_tm_fp)
                self._createOutputTable(travel_modes_resource_response)
                return
            except Exception as ex:
                #Return network dataset travel modes with localizations if present
                #Get the localized travel mode names and descriptions
                if default_localized_travel_modes_file and os.path.exists(default_localized_travel_modes_file):
                    with open(default_localized_travel_modes_file, "r") as tml_fp:
                        travel_modes_all_lang = json.load(tml_fp)
                #Return localized travel mode names and descriptions based on the user language
                culture = culture.lower()
                if culture in travel_modes_all_lang:
                    localized_travel_modes = travel_modes_all_lang[culture] 
                    for travel_mode_id in localized_travel_modes:
                        travel_mode = nds_travel_modes[travel_mode_id]
                        alt_travel_mode_names[travel_mode_id] = travel_mode.get("name", "")
                        travel_mode.update(localized_travel_modes[travel_mode_id])
                self._createOutputTable(nds_travel_modes, alt_travel_mode_names)
                return
        except Exception as ex:
            self._handleExceptionError(ex)

class GetToolInfo(Utilities):
    '''GetToolInfo geoprocessing service'''

    def __init__(self, *args, **kwargs):
        '''Constructor'''

        #Call the base class constructor
        super(GetToolInfo, self).__init__()

        #Store tool parameters as instance attributes
        self.toolInfoFile = kwargs.get("toolInfoFile", None)
        self.serviceName = kwargs.get("serviceName", None)
        self.toolName = kwargs.get("toolName", None)

        #Print tool parameter values for debugging
        if self.logger.DEBUG:
            for param in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(param, kwargs[param]))

        #derived outputs
        self.toolInfo = u""

    def execute(self):
        '''Main execution logic'''

        try:
            #Fail if the toolname is not valid
            if not self.toolName in  NetworkAnalysisService.SERVICE_NAMES[self.serviceName]:
                arcpy.AddIDMessage("ERROR", 30101, u"{0}".format(self.toolName))
                raise InputError

            #Read the tool info from the JSON file
            with open(self.toolInfoFile, "r") as ti_fp:
                tool_info_json = json.load(ti_fp)
            network_dataset_props = tool_info_json["networkDataset"]
            #do not include supported travel modes as we have a separate tool to get travel modes
            if "supportedTravelModes" in network_dataset_props:
                network_dataset_props.pop("supportedTravelModes")
            tool_info = {
                "networkDataset": network_dataset_props,
                "serviceLimits": tool_info_json["serviceLimits"][self.serviceName][self.toolName]
            }
            self.toolInfo = json.dumps(tool_info, ensure_ascii=False, sort_keys=True)

        except Exception as ex:
            self._handleExceptionError(ex)


