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

'''Module implementing utility tools that help in publishing network analysis services.'''

import os
import logging
import ConfigParser
import fnmatch
import json
import urlparse
import urllib2
import io
import uuid
import base64
import locale
import collections
import shutil
import pprint
import time
import xml.dom.minidom as DOM


try:
    import cPickle as pickle
except:
    import pickle

import arcpy
import nas

#module level attributes

class CreateSupportingFiles(object):
    '''class containing the execution logic'''

    ##constants
    
    #Keywords for restriction usage values
    RESTRICTION_USAGE_VALUES = {
        "-1.0": "PROHIBITED",
        "5.0": "AVOID_HIGH",
        "2.0": "AVOID_MEDIUM",
        "1.3": "AVOID_LOW",
        "0.5" : "PREFER_MEDIUM",
        "0.8" : "PREFER_LOW",
        "0.2" : "PREFER_HIGH"
    }

    TOOL_LIMITS = {
        "FindClosestFacilities": collections.OrderedDict((
            ("maximumFeaturesAffectedByPointBarriers", None),
            ("maximumFeaturesAffectedByLineBarriers", None),
            ("maximumFeaturesAffectedByPolygonBarriers", None),
            ("maximumFacilities", None),
            ("maximumFacilitiesToFind", None),
            ("maximumIncidents", None),
            ("forceHierarchyBeyondDistance", None),
            ("forceHierarchyBeyondDistanceUnits", "Miles"),
        )),
        "FindRoutes" : collections.OrderedDict((
            ("maximumFeaturesAffectedByPointBarriers", None),
            ("maximumFeaturesAffectedByLineBarriers", None),
            ("maximumFeaturesAffectedByPolygonBarriers", None),
            ("maximumStops", None),
            ("maximumStopsPerRoute", None),
            ("forceHierarchyBeyondDistance", None),
            ("forceHierarchyBeyondDistanceUnits", "Miles")
        )),
        "GenerateServiceAreas": collections.OrderedDict(( 
            ("maximumFeaturesAffectedByPointBarriers", None),
            ("maximumFeaturesAffectedByLineBarriers", None),
            ("maximumFeaturesAffectedByPolygonBarriers", None),
            ("maximumFacilities", None),
            ("maximumNumberOfBreaks", None),
            ("maximumBreakTimeValue", None),
            ("maximumBreakTimeValueUnits", "Minutes"),
            ("maximumBreakDistanceValue", None),
            ("maximumBreakDistanceValueUnits", "Miles"),
            ("forceHierarchyBeyondBreakTimeValue", None),
            ("forceHierarchyBeyondBreakTimeValueUnits", "Minutes"),
            ("forceHierarchyBeyondBreakDistanceValue", None),
            ("forceHierarchyBeyondBreakDistanceValueUnits", "Miles"),
        )),
        "SolveLocationAllocation": collections.OrderedDict((
            ("maximumFeaturesAffectedByPointBarriers", None),
            ("maximumFeaturesAffectedByLineBarriers", None),
            ("maximumFeaturesAffectedByPolygonBarriers", None),
            ("maximumFacilities", None),
            ("maximumFacilitiesToFind", None),
            ("maximumDemandPoints", None),
            ("forceHierarchyBeyondDistance", None),
            ("forceHierarchyBeyondDistanceUnits", "Miles"),
        )),
        "SolveVehicleRoutingProblem": collections.OrderedDict((
            ("maximumFeaturesAffectedByPointBarriers", None),
            ("maximumFeaturesAffectedByLineBarriers", None),
            ("maximumFeaturesAffectedByPolygonBarriers", None),
            ("maximumOrders", None),
            ("maximumRoutes", None),
            ("maximumOrdersPerRoute", None),
            ("forceHierarchyBeyondDistance", None),
            ("forceHierarchyBeyondDistanceUnits", "Miles"),
        )),
        "EditVehicleRoutingProblem": collections.OrderedDict((
            ("maximumFeaturesAffectedByPointBarriers", None),
            ("maximumFeaturesAffectedByLineBarriers", None),
            ("maximumFeaturesAffectedByPolygonBarriers", None),
            ("maximumOrders", None),
            ("maximumRoutes", None),
            ("maximumOrdersPerRoute", None),
            ("forceHierarchyBeyondDistance", None),
            ("forceHierarchyBeyondDistanceUnits", "Miles"),
        )),
    }

    def __init__(self, *args, **kwargs):
        '''Constructor'''

        #Initialize instance attributes
        self.logger = nas.Logger(nas.LOG_LEVEL)
        self.templateNDS = None
        self.templateNDSDesc = None
        self.templateNDSTravelModes = None
        self.travelModesJSON = None
        
        if self.logger.DEBUG:
            for arg_name in sorted(kwargs):
                self.logger.debug(u"{0}: {1}".format(arg_name, kwargs[arg_name]))

        #Store tool parameter values as instance attributes
        self.networkDatasets = kwargs.get("network_datasets", None)
        if self.networkDatasets:
            self.networkDatasets = nas.strip_quotes(self.networkDatasets.split(";"))
            self.templateNDS = self.networkDatasets[0]
            self.templateNDSDesc = arcpy.Describe(self.templateNDS)

        self.supportingFilesFolder = kwargs.get("supporting_files_folder", None)
        self.localizedTravelModesFolder = kwargs.get("localized_travel_modes_folder", None)
        self.serviceLimits = kwargs.get("service_limits", None)

        #Initialize derived outputs
        self.ndsPropertiesFile = os.path.join(self.supportingFilesFolder, "NetworkDatasetProperties.ini")
        self.travelModesFile = os.path.join(self.supportingFilesFolder, "DefaultTravelModes.json")
        self.localizedTravelModesFile = os.path.join(self.supportingFilesFolder, "DefaultTravelModesLocalized.json")
        self.toolInfoFile = os.path.join(self.supportingFilesFolder, "ToolInfo.json")
        
    def execute(self):
        '''Main execution logic'''
        
        #Create the network dataset properties file
        parser = ConfigParser.SafeConfigParser()
        #Add a new section with property names and values for each network dataset
        for network in self.networkDatasets:
            network_props = self._getNetworkProperties(network)
            parser.add_section(network)
            for prop in sorted(network_props):
                parser.set(network, prop, network_props[prop])

        #Write the properties to a ini file
        self.logger.info(u"Writing network dataset properties to {0}".format(self.ndsPropertiesFile))
        with open(self.ndsPropertiesFile, "w", 0) as config_file:
            parser.write(config_file)

        #Store the default travel modes
        self._getTravelModes()

        #Store network dataset description as JSON
        template_nds_description = self._getNDSDescription()
        
        #Get service limits
        service_limits = self._getServiceLimits()

        #Write tool info with network dataset description and service limits to a json file
        tool_info_json = {
            "networkDataset" : template_nds_description,
            "serviceLimits": service_limits,
        }
        #Save the localized travel modes to a new file
        self.logger.info(u"Saving tool info to {0}".format(self.toolInfoFile))
        self._saveJSONToFile(self.toolInfoFile, tool_info_json)

    def _saveJSONToFile(self, file_path, json_content):
        '''Write out the json content to a file'''

        with io.open(file_path, "wb") as json_fp:
            json_fp.write(json.dumps(json_content, encoding="utf-8", sort_keys=True, indent=2, 
                                     ensure_ascii=False).encode("utf-8"))
            json_fp.write("\n")

    def _getNetworkProperties(self, network):
        '''Populate a dict containing properties for the network dataset'''

        property_names = ("time_attribute", "time_attribute_units", "distance_attribute",
                         "distance_attribute_units", "restrictions", "default_restrictions",
                         "attribute_parameter_values", "feature_locator_where_clause", "Extent",
                         "travel_modes", "default_custom_travel_mode", "walk_time_attribute",
                         "walk_time_attribute_units", "truck_time_attribute", "truck_time_attribute_units",
                         "non_walking_restrictions", "walking_restriction", "trucking_restriction",
                         "time_neutral_attribute", "time_neutral_attribute_units")
        time_units = ('Minutes', 'Hours', 'Days', 'Seconds')
        populate_attribute_parameters = True
        
        esmp_travel_mode_names = ("DRIVING TIME", "DRIVING DISTANCE", "TRUCKING TIME", "TRUCKING DISTANCE",
                                  "WALKING TIME", "WALKING DISTANCE", "RURAL DRIVING TIME", "RURAL DRIVING DISTANCE")
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
        network_properties = dict.fromkeys(property_names)
        
        nds_desc = arcpy.Describe(network)
        nds_type = nds_desc.networkType
        is_sdc_nds = (nds_type == 'SDC')

        #Build a list of restriction, time and distance cost attributes
        #Get default attributes for geodatabase network datasets.
        attributes = nds_desc.attributes
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
                            if param_name.upper() == "RESTRICTION USAGE" and param_default_value in self.RESTRICTION_USAGE_VALUES:
                                param_default_value = self.RESTRICTION_USAGE_VALUES[param_default_value]
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
            all_source_names = [source.name for source in nds_desc.sources]
            turn_source_names = [turn_source.name for turn_source in nds_desc.turnSources]
            source_names = list(set(all_source_names) - set(turn_source_names))
        search_query = [('"' + source_name + '"', "#") for source_name in source_names]
        search_query = [" ".join(s) for s in search_query]
        network_properties["feature_locator_where_clause"] = ";".join(search_query)
        
        #store the extent
        extent = nds_desc.Extent
        extent_coords = (str(extent.XMin),str(extent.YMin), str(extent.XMax),
                        str(extent.YMax))
        network_properties["Extent"] = pickle.dumps(extent_coords)
        
        #Store the travel modes in a dict with key as a two value tuple (travel mode type, isModeTimeBased) 
        #and value as travel mode name
        nds_travel_modes = {k.upper() : v
                            for k,v in arcpy.na.GetTravelModes(nds_desc.catalogPath).iteritems()}
        travel_modes = {}
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
    
    def _getTravelModes(self):
        """Save travel modes used by default for all the routing services."""

        #Store the travel mode name and travel mode ID mappings
        TRAVEL_MODE_IDS = {
            "Driving Time": "FEgifRtFndKNcJMJ",
            "Driving Distance" : "iKjmHuBSIqdEfOVr",
            "Trucking Time" : "ZzzRtYcPLjXFBKwr",
            "Trucking Distance" : "UBaNfFWeKcrRVYIo",
            "Walking Time" : "caFAgoThrvUpkFBW",
            "Walking Distance" : "yFuMFwIYblqKEefX",
            "Rural Driving Time" : "NmNhNDUwZmE1YTlj",
            "Rural Driving Distance" : "Yzk3NjI1NTU5NjVj",
        }
        #File name that contains translations
        LOCALIZED_FILE_NAME = "DefaultTravelModeNamesAndDescriptions.json"
        BOM = u"\ufeff"
        default_travel_mode_name = u""
        default_travel_mode_id = ""
       
        #Get all the travel modes defined in the template network dataset
        self.templateNDSTravelModes = arcpy.na.GetTravelModes(self.templateNDSDesc.catalogPath)
        nds_attributes = self.templateNDSDesc.attributes

        #Get the default travel mode. If the network dataset does not define default travel mode, use any travel mode
        #as default
        if hasattr(self.templateNDSDesc, "defaultTravelModeName"):
            default_travel_mode_name = self.templateNDSDesc.defaultTravelModeName
        if not default_travel_mode_name:
            if "Driving Time" in self.templateNDSTravelModes:
                default_travel_mode_name = "Driving Time"
            else:
                default_travel_mode_name = self.templateNDSTravelModes.iterkeys().next()
        
        #Modify the attribute parameters stored with network dataset travel modes so that they store only those
        #attribute parameters that are relevant to restriction and time and distance attributes used in the travel mode
        travel_modes = {}
        for travel_mode_name in self.templateNDSTravelModes:
            #Generate a new id if a travel mode name is not a esmp travel mode.
            travel_mode_id = TRAVEL_MODE_IDS.get(travel_mode_name, base64.b64encode(uuid.uuid4().hex)[0:16])
            travel_mode = json.loads(unicode(self.templateNDSTravelModes[travel_mode_name]), encoding="utf-8")
            attribute_parameters = travel_mode.get("attributeParameterValues", [])
            applicable_attributes = travel_mode.get("restrictionAttributeNames", []) + [travel_mode.get("timeAttributeName", ""),
                                                                                        travel_mode.get("distanceAttributeName", "") ]
            applicable_attribute_parameters = [attr_param for attr_param in attribute_parameters
                                               if attr_param["attributeName"] in applicable_attributes]

            applicable_attribute_parameters = []
            for attr_param in attribute_parameters:
                if attr_param["attributeName"] in applicable_attributes:
                    #Use string keyword for the restriction usage value
                    if attr_param["parameterName"].upper() == "RESTRICTION USAGE":
                        param_value = "{0:.1f}".format(attr_param["value"])
                        attr_param["value"] = self.RESTRICTION_USAGE_VALUES.get(param_value, param_value)
                    applicable_attribute_parameters.append(attr_param)
            travel_mode["attributeParameterValues"] = applicable_attribute_parameters
            travel_mode["id"] = travel_mode_id
            travel_modes[travel_mode_id] = travel_mode

            #Determine the default travel mode id
            if travel_mode_name == default_travel_mode_name:
                default_travel_mode_id = travel_mode_id

        #Prepare the json to be written to the output file.
        self.travelModesJSON = {
            "supportedTravelModes": travel_modes.values(),
            "defaultTravelMode": default_travel_mode_id,
        }
       
        #Save the JSON descriptions to a file
        self.logger.info(u"Saving travel modes to {0}".format(self.travelModesFile))
        self._saveJSONToFile(self.travelModesFile, self.travelModesJSON)

        #Get localized travel mode names and descriptions
        localized_travel_modes = {}
        if self.localizedTravelModesFolder:
            #Get a list of all the *.json file
            for root, dirs, files in os.walk(self.localizedTravelModesFolder):
                for filename in files:
                    if filename == LOCALIZED_FILE_NAME:
                        with io.open(os.path.join(root,filename), "r", encoding="utf-8") as fp:
                            localized_travel_mode_str = fp.read()
                        if localized_travel_mode_str.startswith(BOM):
                            localized_travel_mode_str = localized_travel_mode_str.lstrip(BOM)
                        localized_travel_modes[os.path.basename(root)] = json.loads(localized_travel_mode_str, "utf-8")
            #Save the localized travel modes to a new file
            self.logger.info(u"Saving localized travel modes to {0}".format(self.localizedTravelModesFile))
            self._saveJSONToFile(self.localizedTravelModesFile, localized_travel_modes)

    def _getNDSDescription(self):
        '''Store the description of the template network dataset as a dict in JSON'''

        attribute_parameter_values = []
        attribute_parameter_prop_names = ("attributeName", "parameterName", "parameterType", "value")
        nds_attributes = []
        nds_attribute_prop_names = ("name", "dataType", "units", "usageType", "parameterNames",
                                    "restrictionUsageParameterName", "trafficSupport")
        nds_traffic_support_type = "NONE"
        
        #Get network dataset traffic support type
        if hasattr(self.templateNDSDesc, "trafficSupportType"):
            nds_traffic_support_type = self.templateNDSDesc.trafficSupportType
        else:
            #Calculate based on other properties
            supports_historical_traffic = self.templateNDSDesc.supportsHistoricalTrafficData
            supports_live_traffic = self.templateNDSDesc.supportsLiveTrafficData

            if supports_historical_traffic:
                if supports_live_traffic:
                    live_traffic_data = self.templateNDSDesc.liveTrafficData
                    if live_traffic_data.trafficFeedLocation:
                        nds_traffic_support_type = "HISTORICAL_AND_LIVE"
                    else:
                        nds_traffic_support_type = "HISTORICAL"
                else:
                    nds_traffic_support_type = "HISTORICAL"

        #Get information about network dataset attributes including attribute parameter values
        for nds_attribute in self.templateNDSDesc.attributes:
            nds_attribute_name = nds_attribute.name
            nds_attribute_traffic_support_type = self._getNDSAttributeTrafficSupportType(nds_attribute,
                                                                                         nds_traffic_support_type)
            nds_attribute_parameter_names = []
            nds_attribute_restriction_usage_parameter_name = None
            parameter_count = nds_attribute.parameterCount
            if parameter_count:
                for i in range(parameter_count):
                    param_name = getattr(nds_attribute, "parameterName" + str(i))
                    nds_attribute_parameter_names.append(param_name)
                    param_data_type = getattr(nds_attribute, "parameterType" + str(i))
                    param_usage_type = getattr(nds_attribute, "parameterUsageType" + str(i))
                    if param_usage_type.lower() == "restriction":
                        nds_attribute_restriction_usage_parameter_name = param_name
                    param_default_value = None
                    if hasattr(nds_attribute, "parameterDefaultValue" + str(i)):
                        param_default_value = str(getattr(nds_attribute, "parameterDefaultValue" + str(i)))
                        #if param_name.upper() == "RESTRICTION USAGE" and param_default_value in self.RESTRICTION_USAGE_VALUES:
                        if nds_attribute_restriction_usage_parameter_name and param_default_value in self.RESTRICTION_USAGE_VALUES:
                            param_default_value = self.RESTRICTION_USAGE_VALUES[param_default_value]

                    attribute_parameter_values.append(dict(zip(attribute_parameter_prop_names,
                                                               (nds_attribute_name, param_name, param_data_type,
                                                                param_default_value)
                                                               )
                                                           )
                                                      )
            
            nds_attributes.append(dict(zip(nds_attribute_prop_names,
                                           (nds_attribute_name, nds_attribute.dataType, nds_attribute.units,
                                            nds_attribute.usageType, nds_attribute_parameter_names,
                                            nds_attribute_restriction_usage_parameter_name,
                                            nds_attribute_traffic_support_type)
                                           )
                                       )
                                  )

        network_dataset_description = {
            "attributeParameterValues": attribute_parameter_values,
            "networkAttributes": nds_attributes,
            "supportedTravelModes": self.travelModesJSON.get("supportedTravelModes", []),
            "trafficSupport": nds_traffic_support_type,
        }
        
        return network_dataset_description

    def _getNDSAttributeTrafficSupportType(self, nds_attribute, nds_traffic_support_type):
        '''Calculates traffic support type for a network dataset attribute'''

        attr_traffic_support_type = "NONE"

        if hasattr(nds_attribute, "trafficSupportType"):
            attr_traffic_support_type = nds_attribute.trafficSupportType
        else:
            #Traffic support type for an attribute with NetworkEdgeTraffic evaluator is equal to the traffic support
            #type of the network dataset.
            evaluator_count = nds_attribute.evaluatorCount
            if evaluator_count:
                for i in range(evaluator_count):
                    evaluator_type = getattr(nds_attribute, "evaluatorType{0}".format(i))
                    if evaluator_type.lower() == "networkedgetraffic":
                        attr_traffic_support_type = nds_traffic_support_type
                        break

        return attr_traffic_support_type

    def _getServiceLimits(self):
        '''return service limits for each tool within a GP service'''

        tool_limits = {}
        if self.serviceLimits:
            for limit in self.serviceLimits.split(";"):
                tool_name, limit_name, limit_value = limit.split(" ")
                if limit_value == "#":
                    limit_value = None
                else:
                    try:
                        limit_value = locale.atof(limit_value)
                    except Exception as ex:
                        pass
                tool_limits.setdefault(tool_name, dict())
                tool_limits[tool_name][limit_name] = limit_value
        else:
            #if service limits is not specified, assume all limits to be None
            tool_limits = self.TOOL_LIMITS

        service_names = nas.NetworkAnalysisService.SERVICE_NAMES
        service_limits = dict.fromkeys(service_names, {})
        for service_name in service_names:
            service_limits[service_name] = {tool_name: tool_limits[tool_name] 
                                            for tool_name in service_names[service_name]}
        return service_limits

class PublishRoutingServices(object):
    '''class containing the execution logic'''

    def __init__(self, *args, **kwargs):
        '''constructor'''

        #Initialize instance attributes
        self.siteAdminToken = {}
        self.agsConnectionFile = None
        self.serviceMapDocument = None
        self.supportingFilesFolder = None
        self.owningSystemUrl = ""
        self.ignoreSSLErrors = False
        self.tokenReferrer = None

        #Write messages to a file and as GP messages
        log_file = os.path.join(kwargs["service_definition_folder"], "PublishRoutingServices.log")
        self.logger = nas.Logger(nas.LOG_LEVEL, log_file)

        #if self.logger.DEBUG:
        self.logger.debug("Input parameter values")
        for arg_name in sorted(kwargs):
            if arg_name == "password":
                if kwargs[arg_name]:
                    self.logger.debug(u"{0}: {1}".format(arg_name, "********"))
                else:
                    self.logger.debug(u"{0}: {1}".format(arg_name, kwargs[arg_name]))
            else:
                self.logger.debug(u"{0}: {1}".format(arg_name, kwargs[arg_name]))

        #Store tool parameter values as instance attributes
        self.networkDatasets = kwargs.get("network_dataset", None)
        if self.networkDatasets:
            self.networkDatasets = nas.strip_quotes(self.networkDatasets.split(";"))
        self.templateNDS = self.networkDatasets[0]
        self.templateNDSDescribe = arcpy.Describe(self.templateNDS)
        self.serverUrl = kwargs.get("server_url", None)
        self.userName = kwargs.get("user_name", None)
        self.password = kwargs.get("password", None)
        self.serverDataFolderPath = kwargs.get("server_data_folder_path", None)
        self.serviceDefinitionFolder = kwargs.get("service_definition_folder", None)

        #Initialize derived outputs
        self.networkAnalysisMapService = ""
        self.networkAnalysisUtilitiesGeoprocessingService = ""
        self.networkAnalysisGeoprocessingService = ""
        self.networkAnalysisSyncGeoprocessingService = ""

    def execute(self):
        '''Main execution logic'''

        ROUTING_SERVICE_FOLDER_NAME = "Routing"
        ROUTING_SERVICE_FOLDER_DESC = "Contains services used to perform network analysis."
        DATA_STORE_ITEM_NAME = "RoutingData"
        SUPPORTING_FILES_FOLDER_NAME = "NDSupportingFiles"

        NA_MAP_SERVICE_NAME = "NetworkAnalysis"
        NA_MAP_SERVICE_SUMMARY = "Supports visualizing historical traffic and performs route, closest facility and service area network analysis in synchronous execution mode."
        NA_MAP_SERVICE_TAGS = "route, closest facility, service area, traffic"
        TRAFFIC_LAYER_MIN_SCALE = 100000

        NA_GP_SERVICE_NAME = "NetworkAnalysis"
        NA_GP_SERVICE_SUMMARY = "Performs route, closest facility, service area, location-allocation, and vehicle routing problem analyses in asynchoronous execution mode."
        NA_GP_SERVICE_TAGS = "route, closest facility, service area, location-allocation, vehicle routing problem, vrp"

        NAUTILS_GP_SERVICE_NAME = "NetworkAnalysisUtilities"
        NAUTILS_GP_SERVICE_SUMMARY = "Contains tools that provide auxiliary information for working with network analysis services available with your portal"
        NAUTILS_GP_SERVICE_TAGS = "travel modes, tool info, network description"


        NASYNC_GP_SERVICE_NAME = "NetworkAnalysisSync"
        NASYNC_GP_SERVICE_SUMMARY = "Performs vehicle routing problem analysis in synchoronous execution mode."
        NASYNC_GP_SERVICE_TAGS = "vehicle routing problem, vrp"

        arcpy.CheckOutExtension("network")

        #Get a site admin token
        self._getAdminToken()

        #Check if the provided user has admin or publisher priviledge
        try:
            admin_info_url = "{0}/admin/info".format(self.serverUrl)
            admin_info_response = nas.make_http_request(admin_info_url, self.siteAdminToken, referer=self.tokenReferrer,
                                                        ignore_ssl_errors=self.ignoreSSLErrors)
        except urllib2.HTTPError as ex:
            #admin info request can fail if the server URL is the web-adaptor url that is not authorized for 
            #server admin access.
            if ex.code == 403:
                self.logger.error("Administrative access is disabled at {0}".format(self.serverUrl))
            else:
                self.logger.error("The following HTTP error occurred when trying to fetch {0}".format(admin_info_url))
                self.logger.error("{0}: {1}".format(ex.code, ex.reason))
            raise arcpy.ExecuteError
        else:
            self.userName = admin_info_response.get("loggedInUser", self.userName).split("::")[-1]
            user_privilege = admin_info_response.get("loggedInUserPrivilege", "")
            if not user_privilege in ("ADMINISTER"):
                self.logger.error("User {0} does not have administrator privilege".format(self.userName))
                raise arcpy.ExecuteError
        
        #Check if service folder name Routing exists. If not create it
        #Get a list of existing service folders
        services_root_url = "{0}/admin/services".format(self.serverUrl)
        services_root_response = nas.make_http_request(services_root_url, self.siteAdminToken,
                                                       referer=self.tokenReferrer, ignore_ssl_errors=self.ignoreSSLErrors)
        service_folders = services_root_response.get("folders", [])
        if ROUTING_SERVICE_FOLDER_NAME in service_folders:
            #Fail if any of the services already exist
            routing_service_folder_response = nas.make_http_request("{0}/{1}".format(services_root_url,
                                                                                     ROUTING_SERVICE_FOLDER_NAME),
                                                                    self.siteAdminToken, referer=self.tokenReferrer,
                                                                    ignore_ssl_errors=self.ignoreSSLErrors)
            expected_service_names = (
                NA_MAP_SERVICE_NAME + ".MapServer",
                NA_GP_SERVICE_NAME + ".GPServer",
                NAUTILS_GP_SERVICE_NAME + ".GPServer",
                NASYNC_GP_SERVICE_NAME + ".GPServer",
            )
            service_exists = False
            for service in routing_service_folder_response.get("services", []):
                service_name = service.get("serviceName", "")
                service_type = service.get("type", "")
                if u"{0}.{1}".format(service_name, service_type) in expected_service_names:
                    self.logger.error(u"A {0} with name {1} already exists in {2} folder".format(service_type.replace("Server", " service"),
                                                                                                 service_name,
                                                                                                 ROUTING_SERVICE_FOLDER_NAME))
                    service_exists = True
            if service_exists:
                raise arcpy.ExecuteError
            else:
                self.logger.info("Using existing {0} service folder to publish services".format(ROUTING_SERVICE_FOLDER_NAME)) 
        else:
            service_folder_create_params = dict(self.siteAdminToken)
            service_folder_create_params["folderName"] = ROUTING_SERVICE_FOLDER_NAME
            service_folder_create_params["description"] = ROUTING_SERVICE_FOLDER_DESC
            service_folder_create_response = nas.make_http_request("{0}/createFolder".format(services_root_url),
                                                                   service_folder_create_params,
                                                                   referer=self.tokenReferrer,
                                                                   ignore_ssl_errors=self.ignoreSSLErrors)
            if service_folder_create_response.get("status", "") == "success":
                self.logger.info("Successfully created {0} service folder".format(ROUTING_SERVICE_FOLDER_NAME))
            else:
                self.logger.error("Failed to create {0} service folder".format(ROUTING_SERVICE_FOLDER_NAME))
                raise arcpy.ExecuteError

        #Create a AGS file with server connection info
        ags_connection_file_name = "server.ags"
        self.agsConnectionFile = os.path.join(self.serviceDefinitionFolder, ags_connection_file_name)
        #For federated servers, create the connection file using the signed in user credentials by not passing
        #an explicit user name and password.
        if self.owningSystemUrl:
             user_name = None
             password = None
        else:
            user_name = self.userName
            password = self.password
        arcpy.mapping.CreateGISServerConnectionFile("ADMINISTER_GIS_SERVICES", self.serviceDefinitionFolder,
                                                    ags_connection_file_name, "{0}/admin".format(self.serverUrl),
                                                    "ARCGIS_SERVER", True, None, user_name, password, True)

        #Register the folder containing the network dataset in the data store
        #If the data store item already exists, remove it
        existing_data_store_items = arcpy.ListDataStoreItems(self.agsConnectionFile, "FOLDER")
        for item in existing_data_store_items:
            if item[0].lower() == DATA_STORE_ITEM_NAME.lower():
                arcpy.RemoveDataStoreItem(self.agsConnectionFile, "FOLDER", DATA_STORE_ITEM_NAME)
                break
        nds_folder = os.path.dirname(os.path.dirname(os.path.dirname(self.templateNDSDescribe.catalogPath)))
        data_store_item_status = arcpy.AddDataStoreItem(self.agsConnectionFile, "FOLDER", DATA_STORE_ITEM_NAME,
                                                        self.serverDataFolderPath, nds_folder)
        if data_store_item_status.lower() == "success":
            self.logger.info("Successfully added {0} entry in the server data store".format(DATA_STORE_ITEM_NAME))
        else:
            self.logger.error("Failed to add {0} entry in the server data store".format(DATA_STORE_ITEM_NAME))
            self.logger.error(data_store_item_status)
            raise arcpy.ExecuteError
        
        #Create a folder to store supporting files. If the folder exists, delete it
        supporting_files_folder = os.path.join(self.serviceDefinitionFolder, SUPPORTING_FILES_FOLDER_NAME)
        if os.path.exists(supporting_files_folder):
            try:
                shutil.rmtree(supporting_files_folder)
            except Exception as ex:
                self.logger.exception(u"Failed to delete {0} folder".format(supporting_files_folder))
                raise arcpy.ExecuteError    
        os.mkdir(supporting_files_folder)
        self.supportingFilesFolder = supporting_files_folder

        #Create supporting files
        create_supporting_files = CreateSupportingFiles(network_datasets=";".join(self.networkDatasets),
                                                        supporting_files_folder=supporting_files_folder)
        try:
            self.logger.info(u"Creating supporting files at {0}".format(supporting_files_folder))
            create_supporting_files.execute()
        except Exception as ex:
            self.logger.exception(u"Failed to create supporting files in {0}".format(supporting_files_folder))
            raise arcpy.ExecuteError

        ##Publish NetworkAnalysis Map service
        
        #Create map document with NA layers that is published as a map service
        self.serviceMapDocument = os.path.join(self.serviceDefinitionFolder, NA_MAP_SERVICE_NAME + ".mxd")
        self.logger.info(u"Creating map document used to publish network analysis map service at {0}".format(self.serviceMapDocument))
        mxd = arcpy.mapping.MapDocument("CURRENT")
        data_frame = arcpy.mapping.ListDataFrames(mxd)[0]

        #Make sure the mxd has only network dataset layers and network dataset layers are visible
        for lyr in arcpy.mapping.ListLayers(mxd, "*", data_frame):
            if lyr.name in self.networkDatasets:
                lyr.visible = True
                lyr.minScale = TRAFFIC_LAYER_MIN_SCALE
            else:
                arcpy.mapping.RemoveLayer(data_frame, lyr)

        #Determine the use by default cost attribute for the network dataset
        for nds_attr in self.templateNDSDescribe.attributes:
            if nds_attr.usageType == "Cost" and nds_attr.useByDefault:
                default_cost_attribute = nds_attr.name
                break
        else:
            default_cost_attribute = nds_attr.name
        
        #Create Closest Facility network analysis layer
        output_cf_layer = arcpy.na.MakeClosestFacilityLayer(self.templateNDS, "ClosestFacility", default_cost_attribute, 
                                                            output_path_shape="TRUE_LINES_WITHOUT_MEASURES").getOutput(0)
        output_cf_layer.visible = False
        arcpy.mapping.AddLayer(data_frame, output_cf_layer, "TOP")

        #Create Service Area network analysis layer
        output_sa_layer = arcpy.na.MakeServiceAreaLayer(self.templateNDS, "ServiceArea", default_cost_attribute,
                                                        hierarchy=False).getOutput(0)
        output_sa_layer.visible = False
        arcpy.mapping.AddLayer(data_frame, output_sa_layer, "TOP")

        #Create Route Network analysis layer
        output_route_layer = arcpy.na.MakeRouteLayer(self.templateNDS, "Route", default_cost_attribute,
                                                     output_path_shape="TRUE_LINES_WITHOUT_MEASURES").getOutput(0)
        output_route_layer.visible = False
        arcpy.mapping.AddLayer(data_frame, output_route_layer, "TOP")

        #Save the map document
        mxd.summary = NA_MAP_SERVICE_SUMMARY
        mxd.tags = NA_MAP_SERVICE_TAGS
        mxd.saveACopy(self.serviceMapDocument)
        
        #Create a sd draft
        na_map_service_sddraft = os.path.join(self.serviceDefinitionFolder, NA_MAP_SERVICE_NAME + "_NAServer.sddraft")
        sddraft_msgs = arcpy.mapping.CreateMapSDDraft(arcpy.mapping.MapDocument(self.serviceMapDocument),
                                                      na_map_service_sddraft, NA_MAP_SERVICE_NAME, 
                                                      "FROM_CONNECTION_FILE", self.agsConnectionFile,
                                                      folder_name=ROUTING_SERVICE_FOLDER_NAME)
        
        self.logger.debug(u"Analyzer messages when analyzing {0}".format(na_map_service_sddraft))
        self.logger.debug(pprint.pformat(sddraft_msgs, indent=2))
        
        #modify SD draft to disable KMLServer and enable NAServer SOE
        doc = DOM.parse(na_map_service_sddraft)
        type_names = doc.getElementsByTagName('TypeName')
        for type_name in type_names:
            # Get the TypeName we want to disable.
            if type_name.firstChild.data == "KmlServer":
                extension = type_name.parentNode
                for ext_element in extension.childNodes:
                    # Disable SOE.
                    if ext_element.tagName == 'Enabled':
                        ext_element.firstChild.data = 'false'
            elif type_name.firstChild.data == "NAServer":
                extension = type_name.parentNode
                for ext_element in extension.childNodes:
                    # Enable SOE.
                    if ext_element.tagName == 'Enabled':
                        ext_element.firstChild.data = 'true'
        with open(na_map_service_sddraft, "w") as sddraft_fp:
            doc.writexml(sddraft_fp)

        #Publish SD draft as SD
        if self.logger.DEBUG:
            shutil.copy2(na_map_service_sddraft, na_map_service_sddraft + ".xml")
        na_map_service_sd = os.path.join(self.serviceDefinitionFolder, NA_MAP_SERVICE_NAME + "_NAServer.sd")
        self.logger.info("Creating network analysis map service definition at {0}".format(na_map_service_sd))
        arcpy.server.StageService(na_map_service_sddraft, na_map_service_sd)
        
        ##Publish NetworkAnalysisUtilities GP service
        self.logger.info("Running geoprocessing tools to publish network analysis utilities geoprocessing service")
        #Import the toolbox
        tbx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NetworkAnalysisTools.pyt")
        nast = arcpy.ImportToolbox(tbx)

        #Run the GetTravelModes and GetToolInfo tools
        get_tool_info_result = nast.GetToolInfo(supporting_files_folder)
        get_tm_result = nast.GetTravelModes([[os.path.join(supporting_files_folder, "DefaultTravelModes.json"),
                                                   "Default Travel Modes File"]])
        #Create the SD draft
        nautils_gpservice_sddraft = os.path.join(self.serviceDefinitionFolder, NAUTILS_GP_SERVICE_NAME + "_GPServer.sddraft")

        sddraft_msgs = arcpy.CreateGPSDDraft([get_tool_info_result, get_tm_result], nautils_gpservice_sddraft,
                                             NAUTILS_GP_SERVICE_NAME, "FROM_CONNECTION_FILE", self.agsConnectionFile,
                                             False, ROUTING_SERVICE_FOLDER_NAME, NAUTILS_GP_SERVICE_SUMMARY,
                                             NAUTILS_GP_SERVICE_TAGS, "Synchronous", False, "Warning")
        self.logger.debug(u"Analyzer messages when analyzing {0}".format(nautils_gpservice_sddraft))
        self.logger.debug(pprint.pformat(sddraft_msgs, indent=2))
        if self.logger.DEBUG:
            shutil.copy2(nautils_gpservice_sddraft, nautils_gpservice_sddraft + ".xml") 
        
        #Publish SD draft as SD    
        nautils_gp_service_sd = os.path.join(self.serviceDefinitionFolder, NAUTILS_GP_SERVICE_NAME + "_GPServer.sd")
        self.logger.info("Creating network analysis utilities geoprocessing service definition at {0}".format(nautils_gp_service_sd))
        arcpy.server.StageService(nautils_gpservice_sddraft, nautils_gp_service_sd)

        ##Publish Network Analysis Geoprocessing service
        #Use the endpoints of the first feature in the streets edge source as the inputs for gp services
        system_junctions_feature_class = os.path.join(os.path.dirname(self.templateNDSDescribe.catalogPath), 
                                                      self.templateNDSDescribe.systemJunctionSource.name)
        with arcpy.da.SearchCursor(system_junctions_feature_class, "SHAPE@") as cursor:
            street_points = [cursor.next()[0], cursor.next()[0]]

        self.logger.info("Running geoprocessing tools to publish network analysis geoprocessing service")

        rt_stops = "in_memory\\InputRouteStops"
        arcpy.management.CopyFeatures(street_points, rt_stops)
        find_routes_result = nast.FindRoutes(rt_stops, "Minutes", supporting_files_folder)

        incidents = "in_memory\\InputIncidents"
        facilities = "in_memory\\InputFacilities"
        arcpy.management.CopyFeatures(street_points[0], incidents)
        arcpy.management.CopyFeatures(street_points[1], facilities)
        find_cf_result = nast.FindClosestFacilities(incidents, facilities, "Minutes", supporting_files_folder)
        
        generate_sa_result = nast.GenerateServiceAreas(facilities, "5 10 15", "Minutes", supporting_files_folder)

        solve_la_result = nast.SolveLocationAllocation(facilities, incidents, "Minutes", supporting_files_folder)

        vrp_routes = arcpy.GetParameterValue("SolveVehicleRoutingProblem_nast", 2)
        with arcpy.da.InsertCursor(vrp_routes, ("Name", "StartDepotName", "EndDepotName")) as cursor:
            cursor.insertRow(("r", "d", "d"))
        vrp_depots = arcpy.GetParameterValue("SolveVehicleRoutingProblem_nast", 1)
        with arcpy.da.InsertCursor(vrp_depots, ("SHAPE@", "Name")) as cursor:
            cursor.insertRow((street_points[1], "d"))
        solve_vrp_result = nast.SolveVehicleRoutingProblem(incidents, vrp_depots, vrp_routes, "", "Minutes", "Miles",
                                                           supporting_files_folder)

        #Create the SD draft
        na_gpservice_sddraft = os.path.join(self.serviceDefinitionFolder, NA_GP_SERVICE_NAME + "_GPServer.sddraft")
        sddraft_msgs = arcpy.CreateGPSDDraft([find_routes_result,
                                              find_cf_result,
                                              generate_sa_result,
                                              solve_la_result,
                                              solve_vrp_result],
                                             na_gpservice_sddraft, NA_GP_SERVICE_NAME, "FROM_CONNECTION_FILE",
                                             self.agsConnectionFile, False, ROUTING_SERVICE_FOLDER_NAME,
                                             NA_GP_SERVICE_SUMMARY, NA_GP_SERVICE_TAGS, "Asynchronous", False,
                                             "Warning")
        self.logger.debug(u"Analyzer messages when analyzing {0}".format(na_gpservice_sddraft))
        self.logger.debug(pprint.pformat(sddraft_msgs, indent=2))
        if self.logger.DEBUG:
            shutil.copy2(na_gpservice_sddraft, na_gpservice_sddraft + ".xml") 
        
        #Publish SD draft as SD    
        na_gp_service_sd = os.path.join(self.serviceDefinitionFolder, NA_GP_SERVICE_NAME + "_GPServer.sd")
        self.logger.info("Creating network analysis geoprocessing service definition at {0}".format(na_gp_service_sd))
        arcpy.server.StageService(na_gpservice_sddraft, na_gp_service_sd)

        ##Publish NetworkAnalysisSync GP service
        self.logger.info("Running geoprocessing tools to publish network analysis sync geoprocessing service")
        edit_vrp_result = nast.EditVehicleRoutingProblem(incidents, vrp_depots, vrp_routes, "", "Minutes", "Miles",
                                                         supporting_files_folder)
        #Create the SD draft
        nasync_gpservice_sddraft = os.path.join(self.serviceDefinitionFolder,
                                                NASYNC_GP_SERVICE_NAME + "_GPServer.sddraft")
        sddraft_msgs = arcpy.CreateGPSDDraft(edit_vrp_result, nasync_gpservice_sddraft, NASYNC_GP_SERVICE_NAME,
                                             "FROM_CONNECTION_FILE", self.agsConnectionFile, False,
                                             ROUTING_SERVICE_FOLDER_NAME, NASYNC_GP_SERVICE_SUMMARY,
                                             NASYNC_GP_SERVICE_TAGS, "Synchronous", False, "Warning")
        self.logger.debug(u"Analyzer messages when analyzing {0}".format(nasync_gpservice_sddraft))
        self.logger.debug(pprint.pformat(sddraft_msgs, indent=2))
        if self.logger.DEBUG:
            shutil.copy2(nasync_gpservice_sddraft, nasync_gpservice_sddraft + ".xml") 

        #Publish SD draft as SD    
        nasync_gp_service_sd = os.path.join(self.serviceDefinitionFolder, NASYNC_GP_SERVICE_NAME + "_GPServer.sd")
        self.logger.info("Creating network analysis sync geoprocessing service definition at {0}".format(nasync_gp_service_sd))
        arcpy.server.StageService(nasync_gpservice_sddraft, nasync_gp_service_sd)
        
        #na_map_service_sd = os.path.join(self.serviceDefinitionFolder, NA_MAP_SERVICE_NAME + "_NAServer.sd")
        #nautils_gp_service_sd = os.path.join(self.serviceDefinitionFolder, NAUTILS_GP_SERVICE_NAME + "_GPServer.sd")
        #na_gp_service_sd = os.path.join(self.serviceDefinitionFolder, NA_GP_SERVICE_NAME + "_GPServer.sd")
        #nasync_gp_service_sd = os.path.join(self.serviceDefinitionFolder, NASYNC_GP_SERVICE_NAME + "_GPServer.sd")

        ##Publish the SD's as services
        self.logger.info("Publishing service definitions as services")
        
        na_map_service_result = arcpy.server.UploadServiceDefinition(na_map_service_sd, self.agsConnectionFile)
        self.logger.debug(na_map_service_result.getMessages())
        self.networkAnalysisMapService = na_map_service_result.getOutput(1)

        nautils_gp_service_result = arcpy.server.UploadServiceDefinition(nautils_gp_service_sd, self.agsConnectionFile)
        self.logger.debug(nautils_gp_service_result.getMessages())
        self.networkAnalysisUtilitiesGeoprocessingService = nautils_gp_service_result.getOutput(1)

        na_gp_service_result = arcpy.server.UploadServiceDefinition(na_gp_service_sd, self.agsConnectionFile)
        self.logger.debug(na_gp_service_result.getMessages())
        self.networkAnalysisGeoprocessingService = na_gp_service_result.getOutput(1)

        nasync_gp_service_result = arcpy.server.UploadServiceDefinition(nasync_gp_service_sd, self.agsConnectionFile)
        self.logger.debug(nautils_gp_service_result.getMessages())
        self.networkAnalysisSyncGeoprocessingService = nasync_gp_service_result.getOutput(1)
        
        ##Share services with Portal for ArcGIS and configure them as utility services.
        CONFIG_UTIL_SVCS_MSG = "Please follow the instructions from {} to configure the routing services as utility services in your portal using the portal website"
        if self.owningSystemUrl:

            #The token might have expired by the time execution reaches here. So get a new token
            signed_in_token = arcpy.GetSigninToken()             
            self.siteAdminToken["token"] = signed_in_token["token"]
            self.tokenReferrer = signed_in_token.get("referer", "")
            token_expiry = time.asctime(time.localtime(signed_in_token.get("expires", 0)))
            self.logger.debug("Renewed the portal token that is valid untill: {}".format(token_expiry))
            
            #Check if the sharing API calls can be made using owning system URL. This works only if the portal
            #is configured with BUILTIN authentication
            sharing_root_url = "{}/sharing/rest".format(self.owningSystemUrl)
            try:
                sharing_root_response = nas.make_http_request(sharing_root_url, self.siteAdminToken,
                                                              referer=self.tokenReferrer)
            except urllib2.URLError as ex:
                #Portal is using web tier authentication. Try using private portal url
                self.logger.debug("Determining the private portal url")
                server_security_config_url = "{}/admin/security/config".format(self.serverUrl)
                server_security_config = nas.make_http_request(server_security_config_url, self.siteAdminToken,
                                                               referer=self.tokenReferrer,
                                                               ignore_ssl_errors=True)
                self.owningSystemUrl = server_security_config["portalProperties"]["privatePortalUrl"]
                sharing_root_url = "{}/sharing/rest".format(self.owningSystemUrl)
                try:
                    self.logger.debug("Checking if the sharing API can be accessed using the private portal URL, {}".format(sharing_root_url))
                    sharing_root_response = nas.make_http_request(sharing_root_url, self.siteAdminToken,
                                                                  referer=self.tokenReferrer,
                                                                  ignore_ssl_errors=True)
                except Exception as ex:
                    #Exit and inform that the routing services needs to manually configured as utility services
                    self.logger.warning("The tool cannot configure the routing services as utility services in your portal.")
                    self.logger.warning(CONFIG_UTIL_SVCS_MSG.format("http://esriurl.com/crusffs"))
                    self.logger.fileLogger.exception("Failed to make sharing API calls with private portal URL")
                    return
            #Share services with organization
            self.logger.info("Sharing services with Portal for ArcGIS")
            self.logger.debug("Making sharing API calls using {}".format(self.owningSystemUrl))
            #Store the portal item ids for the services.
            service_item_ids = {}
            #Get a list of service URLs in the service folder
            service_folder_url = "{0}/{1}".format(services_root_url, ROUTING_SERVICE_FOLDER_NAME)
            service_folder_response = nas.make_http_request(service_folder_url, self.siteAdminToken,
                                                            referer=self.tokenReferrer, ignore_ssl_errors=self.ignoreSSLErrors)
            for service in service_folder_response.get("services", []):
                #Create URL to get service properties
                portal_service_name = service["serviceName"]
                service_properties_url = "{0}/{1}.{2}".format(service_folder_url, portal_service_name, service["type"])
                service_properties = nas.make_http_request(service_properties_url, self.siteAdminToken,
                                                           referer=self.tokenReferrer, ignore_ssl_errors=self.ignoreSSLErrors)
                for item in service_properties["portalProperties"]["portalItems"]:
                    service_item_ids["{}.{}".format(portal_service_name, item["type"])] = item["itemID"]
    
            #share the items
            share_items_url = "{0}/sharing/rest/content/users/{1}/shareItems".format(self.owningSystemUrl,
                                                                                     self.userName)
            share_items_query_params = dict(self.siteAdminToken)
            share_items_query_params["everyone"] = False
            share_items_query_params["account"] = True
            share_items_query_params["items"] = ",".join(service_item_ids.values())
            share_items_response = nas.make_http_request(share_items_url, share_items_query_params,
                                                         referer=self.tokenReferrer, ignore_ssl_errors=True)
            self.logger.debug(json.dumps(share_items_response, ensure_ascii=False, indent=2))

            #Update the REST URLs for the routing services to be the ones accessible from the portal
            user_items_url = "{0}/sharing/rest/content/users/{1}/items".format(self.owningSystemUrl, self.userName)
            #NA GP service
            service_item_property_url = "{}/{}".format(user_items_url,
                                                       service_item_ids["{}.GPServer".format(NA_GP_SERVICE_NAME)]) 
            
            service_item_property_response = nas.make_http_request(service_item_property_url, self.siteAdminToken,
                                                                   referer=self.tokenReferrer, ignore_ssl_errors=True)
            self.networkAnalysisGeoprocessingService = service_item_property_response["item"]["url"]
            #NA Sync GP service
            service_item_property_url = "{}/{}".format(user_items_url,
                                                       service_item_ids["{}.GPServer".format(NASYNC_GP_SERVICE_NAME)]) 
            service_item_property_response = nas.make_http_request(service_item_property_url, self.siteAdminToken,
                                                                   referer=self.tokenReferrer, ignore_ssl_errors=True)
            self.networkAnalysisSyncGeoprocessingService = service_item_property_response["item"]["url"]
            #NA Utilities GP service
            service_item_property_url = "{}/{}".format(user_items_url,
                                                       service_item_ids["{}.GPServer".format(NAUTILS_GP_SERVICE_NAME)]) 
            service_item_property_response = nas.make_http_request(service_item_property_url, self.siteAdminToken,
                                                                   referer=self.tokenReferrer, ignore_ssl_errors=True)
            self.networkAnalysisUtilitiesGeoprocessingService = service_item_property_response["item"]["url"]
            #NA Map Service
            service_item_property_url = "{}/{}".format(user_items_url,
                                                       service_item_ids["{}.MapServer".format(NA_MAP_SERVICE_NAME)]) 
            service_item_property_response = nas.make_http_request(service_item_property_url, self.siteAdminToken,
                                                                   referer=self.tokenReferrer, ignore_ssl_errors=True)
            self.networkAnalysisMapService = service_item_property_response["item"]["url"]
            #NA NAServer Service
            service_item_property_url = "{}/{}".format(user_items_url,
                                                       service_item_ids["{}.NAServer".format(NA_MAP_SERVICE_NAME)]) 
            service_item_property_response = nas.make_http_request(service_item_property_url, self.siteAdminToken,
                                                                   referer=self.tokenReferrer, ignore_ssl_errors=True)
            network_analysis_naserver_service = service_item_property_response["item"]["url"]
            #modify portals/self call to return REST endpoints of services
            self.logger.info("Configuring routing services as utility services")
            portals_self_update_url = "{0}/sharing/rest/portals/self/update".format(self.owningSystemUrl)
    
            closest_facility_sync_url = "{}/ClosestFacility".format(network_analysis_naserver_service)
            closest_facility_async_url = "{}/FindClosestFacilities".format(self.networkAnalysisGeoprocessingService)
            service_area_sync_url = "{}/ServiceArea".format(network_analysis_naserver_service)
            service_area_async_url = "{}/GenerateServiceAreas".format(self.networkAnalysisGeoprocessingService)
            vrp_sync_url = "{}/EditVehicleRoutingProblem".format(self.networkAnalysisSyncGeoprocessingService)
            vrp_async_url = "{}/SolveVehicleRoutingProblem".format(self.networkAnalysisGeoprocessingService)
            route_sync_url = "{}/Route".format(network_analysis_naserver_service)
            route_async_url = "{}".format(self.networkAnalysisGeoprocessingService)
            location_allocation_async_url = "{}".format(self.networkAnalysisGeoprocessingService)
            routing_utlities_url = "{}".format(self.networkAnalysisUtilitiesGeoprocessingService)
            traffic_url = "{}".format(self.networkAnalysisMapService)
    
            portals_self_update_query_params = dict(self.siteAdminToken)
            portals_self_update_query_params['asyncClosestFacilityService'] = {"url": closest_facility_async_url}
            portals_self_update_query_params['asyncLocationAllocationService'] = {"url": location_allocation_async_url}
            portals_self_update_query_params['asyncRouteService'] = {"url": route_async_url}
            portals_self_update_query_params['asyncServiceAreaService'] = {"url": service_area_async_url}
            portals_self_update_query_params['syncVRPService'] = {"url": vrp_sync_url}
            portals_self_update_query_params['asyncVRPService'] = {"url": vrp_async_url}
            portals_self_update_query_params['closestFacilityService'] = {"url": closest_facility_sync_url}
            portals_self_update_query_params['routeServiceLayer'] = {"url": route_sync_url}
            portals_self_update_query_params['routingUtilitiesService'] = {"url": routing_utlities_url}
            portals_self_update_query_params['serviceAreaService'] = {"url": service_area_sync_url}
            portals_self_update_query_params['trafficService'] = {"url": traffic_url}

            portals_self_update_response = nas.make_http_request(portals_self_update_url, portals_self_update_query_params,
                                                                 referer=self.tokenReferrer, ignore_ssl_errors=True)
            self.logger.debug(json.dumps(portals_self_update_response, ensure_ascii=False, indent=2))
        else:
            #Add a message about manually configuring utility services
            self.logger.info("The following routing services have been successfully published to your GIS server")
            self.logger.info(self.networkAnalysisMapService)
            self.logger.info(self.networkAnalysisUtilitiesGeoprocessingService)
            self.logger.info(self.networkAnalysisGeoprocessingService)
            self.logger.info(self.networkAnalysisSyncGeoprocessingService)
            self.logger.info(CONFIG_UTIL_SVCS_MSG.format("http://esriurl.com/crusfnfs"))

    def cleanup(self):
        '''Delete intermidiate files and folders'''

        #skip cleanup if log level is DEBUG
        if self.logger.DEBUG:
            return
        #Delete intermidiate files
        for f in (self.agsConnectionFile, self.serviceMapDocument):
            if f:
                try:
                    os.remove(f)
                except Exception as ex:
                    self.logger.debug(str(ex))
                    self.logger.debug("Fail to delete {}".format(f))
        #Delete intermidiate folders
        if self.supportingFilesFolder:
            shutil.rmtree(self.supportingFilesFolder, ignore_errors=True)

        #Close the file handler
        self.logger.fileLogger.handlers[0].close()

    def _getAdminToken(self):
        '''Perform checks for successful execution. Raise an execute error if a check fails'''

       
        #Local names used in this method
        token_url = ""
        owning_system_url = ""
        ERR_URL_FETCH = u"An error occured when trying to fetch {0}. Check if ArcGIS Server is running"
        ERR_SSL_CERT_TRUST = u"The GIS Server's SSL certificate is not installed as a trusted certificate. Import the certificate into the OS certificate store by following instructions from http://esriurl.com/oscertstore"
        ERR_INVALID_SERVER_URL = u"{} is not a valid Server URL"
        ERR_MISSING_WEB_ADAPTOR = u"The Server URL, {}, does not include the web adaptor name"
        ERR_NOT_SIGNED_IN_PORTAL = u"Sign in to portal, {}, from ArcGIS Desktop as a user with administrator privilege. You can follow instructions from http://esriurl.com/cpdesktop to connect to Portal for ArcGIS via ArcGIS Desktop"  
        #Admin access is usually enabled only on ports 6080 and 6443. So ignore any ssl errors when making 
        #Admin API calls.
        self.ignoreSSLErrors = True 

        #Check that server URL only includes server name and web adaptor name
        server_url_parts = urlparse.urlsplit(self.serverUrl)
        if not server_url_parts.scheme in ("http", "https"):
            self.logger.error(ERR_INVALID_SERVER_URL.format(self.serverUrl))
            raise arcpy.ExecuteError

        url_path = server_url_parts.path.rstrip("/").lstrip("/")
        web_adaptor_name = url_path.split("/")[0]
        if not web_adaptor_name:
            self.logger.error(ERR_MISSING_WEB_ADAPTOR.format(self.serverUrl))
            raise arcpy.ExecuteError
        
        #update the server url to only include the hostname and web adaptor name
        self.serverUrl = "{0}://{1}/{2}".format(server_url_parts.scheme, server_url_parts.netloc, web_adaptor_name)
        self.logger.debug(u"Updated server URL: {0}".format(self.serverUrl))

        #Get the owning system url to determine if the server is federated
        rest_info_url = "{0}/rest/info".format(self.serverUrl)
        try:
            #Fail if we get SSL verification errors. 
            rest_info_response = nas.make_http_request(rest_info_url, ignore_ssl_errors=False)
        except urllib2.URLError as ex:
            if ex.args and len(ex.args):
                ssl_obj = ex.args[0]
                if hasattr(ssl_obj, "reason"):
                    if ssl_obj.reason == "CERTIFICATE_VERIFY_FAILED":
                        self.logger.error(ERR_SSL_CERT_TRUST)
                        raise arcpy.ExecuteError
                    else:
                        self.logger.error(ERR_URL_FETCH.format(rest_info_url))
                        raise arcpy.ExecuteError
                else:
                    self.logger.error(ERR_URL_FETCH.format(rest_info_url))
                    raise arcpy.ExecuteError
            else:
                self.logger.error(ERR_URL_FETCH.format(rest_info_url))
                raise arcpy.ExecuteError
        except Exception as ex:
            self.logger.error(ERR_URL_FETCH.format(rest_info_url))
            raise arcpy.ExecuteError
        else:
            owning_system_url = rest_info_response.get("owningSystemUrl", "")
            if owning_system_url:
                self.owningSystemUrl = owning_system_url
                #Use the token of the user signed in to ArcMap.
                #Make sure ArcMap is using the same portal and the owning system of the server
                active_portal_url = arcpy.GetActivePortalURL().rstrip("/")
                ERR_NOT_SIGNED_IN_PORTAL = ERR_NOT_SIGNED_IN_PORTAL.format(owning_system_url) 
                if active_portal_url.lower() != owning_system_url.lower():
                    self.logger.error(ERR_NOT_SIGNED_IN_PORTAL)
                    raise arcpy.ExecuteError
                signed_in_token = arcpy.GetSigninToken()
                if signed_in_token is None:
                    self.logger.error(ERR_NOT_SIGNED_IN_PORTAL)
                    raise arcpy.ExecuteError
                site_admin_token = signed_in_token.get("token", "")
                self.tokenReferrer = signed_in_token.get("referer", "")
                self.logger.debug("Got a portal token that is valid untill: {}".format(time.asctime(time.localtime(signed_in_token.get("expires", 0)))))
                if not site_admin_token:
                    self.logger.error(ERR_NOT_SIGNED_IN_PORTAL)
                    raise arcpy.ExecuteError
                if self.userName:
                    self.logger.warning("The value for the User Name parameter is ignored as you are signed into a portal.")
                if self.password:
                    self.logger.warning("The value for the Password parameter is ignored as your are signed into a portal.")

            else:
                #get a admin token as the server is not federated
                self.owningSystemUrl = ""
                token_url = "{0}/admin/generateToken".format(self.serverUrl)
                self.tokenReferrer = self.serverUrl
                token_params = {
                    "username" : self.userName,
                    "password" : self.password,
                    "client" : "referer",
                    "referer" : self.tokenReferrer,
                }
        
                #Get a server admin token
                token_response = nas.make_http_request(token_url, token_params, ignore_ssl_errors=self.ignoreSSLErrors)

                site_admin_token = token_response.get("token", "")
                if not site_admin_token:
                    self.logger.error("Invalid User Name or Password")
                    raise arcpy.ExecuteError
                token_validity = time.asctime(time.localtime(int(token_response.get("expires", 0)) / 1000))
                self.logger.debug("Got a server token that is valid untill: {}".format(token_validity))
        self.siteAdminToken = {
            "token": site_admin_token,
            "f": "json",
        }
    
        
