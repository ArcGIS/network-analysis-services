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

import os
import arcpy
import ut

class Toolbox(object):
    def __init__(self):
        '''Define the toolbox (the name of the toolbox is the name of the
        .pyt file).'''
        
        self.label = "Utility Tools"
        self.alias = "naut"
        self.tools = [CreateSupportingFiles, PublishRoutingServices]

class CreateSupportingFiles(object):
    
    def __init__(self):
        '''Define the tool (tool name is the name of the class).'''
    
        self.label = "Create Supporting Files"
        self.description = ""
        self.canRunInBackground = False
        self.category = ""
    
    def getParameterInfo(self):
        '''Define parameter definitions'''

        #Network Datasets parameter
        network_datasets_param = arcpy.Parameter("network_datasets", "Network Datasets", "Input",
                                                 "GPNetworkDatasetLayer", "Required", multiValue=True)
        
        #Supporting Files Folder parameter
        supporting_files_folder_param = arcpy.Parameter("supporting_files_folder", "Supporting Files Folder", "Input",
                                                        "DEFolder", "Required")

        #Localized travel modes folder parameter
        localized_travel_modes_folder_param = arcpy.Parameter("localized_travel_modes_folder",
                                                              "Localized Travel Modes Folder", "Input", "DEFolder",
                                                              "Optional")
        #Service limits parameter
        service_limits_param = arcpy.Parameter("service_limits", "Service Limits", "Input", "GPValueTable", "Optional")
        service_limits_param.category = "Service Limits"
        service_limits_param.columns = [["GPString", "Tool Name"], ["GPString", "Constraint"], ["GPString", "Value"]]
        service_limits_param.filters[0].type = "ValueList"
        service_limits_param.filters[1].type = "ValueList"
        service_limits_param.filters[0].list = sorted(ut.CreateSupportingFiles.TOOL_LIMITS.keys())
        service_limits_param.filters[1].list = sorted(list({limit_name 
                                                            for limit_names in ut.CreateSupportingFiles.TOOL_LIMITS.itervalues()
                                                            for limit_name in limit_names}))
        service_limits_param.values = [[tool_name, limit_name, limit_value]
                                       for tool_name, tool_limits in sorted(ut.CreateSupportingFiles.TOOL_LIMITS.iteritems())
                                       for limit_name, limit_value in tool_limits.iteritems()]

        #Derived outputs
        network_dataset_properties_file_param = arcpy.Parameter("network_dataset_properties_file",
                                                                "Network Dataset Properties File", "Output", "DEFile",
                                                                "Derived")
        travel_modes_file_param = arcpy.Parameter("travel_modes_file", "Travel Modes File", "Output", "DEFile",
                                                  "Derived")
        localized_travel_modes_file_param = arcpy.Parameter("localized_travel_modes_file",
                                                            "Localized Travel Modes File", "Output", "DEFile",
                                                            "Derived")
        tool_info_file_param = arcpy.Parameter("tool_info_file", "Tool Info File", "Output", "DEFile", "Derived")
               
        params = [network_datasets_param, supporting_files_folder_param, localized_travel_modes_folder_param,
                  service_limits_param, network_dataset_properties_file_param, travel_modes_file_param,
                  localized_travel_modes_file_param, tool_info_file_param]
        return params
    
    def isLicensed(self):
        '''Set whether tool is licensed to execute.'''
        return True
    
    def updateParameters(self, parameters):
        '''Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed.'''

        #Store references to frequently used parameter objects
        network_datasets_param = parameters[0]
        supporting_files_folder_param = parameters[1]
        service_limits_param = parameters[3]

        #Add all the network dataset layers from the first data frame in the current map document as the default
        #value for the network datasets parameter
        template_nds = None
        if not network_datasets_param.valueAsText:
            default_network_datasets = []
            mxd = arcpy.mapping.MapDocument("CURRENT")
            data_frame = arcpy.mapping.ListDataFrames(mxd)[0]
            for layer in  arcpy.mapping.ListLayers(mxd, "*", data_frame):
                if layer.supports("DATASOURCE"):
                    #Skip layers that cannot be described as they are also not network dataset layers
                    try:
                        nds_desc = arcpy.Describe(layer)
                        layer_type = nds_desc.dataType
                        if layer_type.lower() == "networkdatasetlayer":
                            default_network_datasets.append(layer.name)
                            #Store the first nds as template nds
                            if not template_nds:
                                template_nds = layer
                    except Exception as ex:
                        pass 
            if default_network_datasets:
                network_datasets_param.value = default_network_datasets

        #Set the default value for supporting files folder to be folder containing the first network dataset
        if not supporting_files_folder_param.valueAsText and not supporting_files_folder_param.altered:
            if template_nds:
                supporting_files_folder_param.value = os.path.dirname(template_nds.workspacePath)
                
        return

    def updateMessages(self, parameters):
        '''Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation.'''
        return

    def execute(self, parameters, messages):
        '''The source code of the tool.'''

        tool_parameters = {param.name : param.valueAsText for param in parameters}

        
        create_supporting_files = ut.CreateSupportingFiles(**tool_parameters)
        create_supporting_files.execute()

        #Set the derived outputs

        derived_output_start_index = 4
        arcpy.SetParameterAsText(derived_output_start_index, create_supporting_files.ndsPropertiesFile)
        arcpy.SetParameterAsText(derived_output_start_index + 1, create_supporting_files.travelModesFile)
        arcpy.SetParameterAsText(derived_output_start_index + 2, create_supporting_files.localizedTravelModesFile)
        arcpy.SetParameterAsText(derived_output_start_index + 3, create_supporting_files.toolInfoFile)

class PublishRoutingServices(object):
    '''ArcGIS geoprocessing tool that publishes routing services to ArcGIS Server.'''

    def __init__(self):
        '''Define the tool (tool name is the name of the class).'''
    
        self.label = "Publish Routing Services"
        self.description = ""
        self.canRunInBackground = False
        self.category = ""
    
    def getParameterInfo(self):
        '''Define parameter definitions'''

        #Network Datasets parameter
        network_dataset_param = arcpy.Parameter("network_dataset", "Network Dataset", "Input",
                                                 "GPNetworkDatasetLayer", "Required", multiValue=False)
       
        #Service definition folder
        service_definition_folder_param = arcpy.Parameter("service_definition_folder", "Service Definition Folder", 
                                                          "Input", "DEFolder", "Required")
        #Server data folder path parameter
        server_data_folder_path_param = arcpy.Parameter("server_data_folder_path", "Server Data Folder Path", "Input",
                                                        "GPString", "Required")
        #Server URL parameter
        server_url_param = arcpy.Parameter("server_url", "Server URL", "Input", "GPString", "Required")
        server_url_param.value = "http://localhost:6080/arcgis"

        #User Name parameter
        user_name_param = arcpy.Parameter("user_name", "User Name", "Input", "GPString", "Optional")

        #Password parameter
        password_param = arcpy.Parameter("password", "Password", "Input", "GPStringHidden", "Optional")

        #Derived outputs
        network_analysis_map_service_param = arcpy.Parameter("network_analysis_map_service",
                                                             "Network Analysis Map Service", "Output", "GPString",
                                                             "Derived")
        network_analysis_utilities_gp_service_param = arcpy.Parameter("network_analysis_utilities_geoprocessing_service",
                                                                      "Network Analysis Utilities Geoprocessing Service",
                                                                      "Output", "GPString", "Derived")
        network_analysis_gp_service_param = arcpy.Parameter("network_analysis_geoprocessing_service",
                                                            "Network Analysis Geoprocessing Service", "Output",
                                                            "GPString", "Derived")
        network_analysis_sync_gp_service_param = arcpy.Parameter("network_analysis_sync_geoprocessing_service",
                                                                 "Network Analysis Sync Geoprocessing Service",
                                                                 "Output", "GPString", "Derived")

               
        params = [network_dataset_param, service_definition_folder_param, server_data_folder_path_param,
                  server_url_param, user_name_param, password_param, network_analysis_map_service_param,
                  network_analysis_utilities_gp_service_param, network_analysis_gp_service_param,
                  network_analysis_sync_gp_service_param]
        return params
    
    def isLicensed(self):
        '''Set whether tool is licensed to execute.'''
        return True
    
    def updateParameters(self, parameters):
        '''Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed.'''

        #Store references to frequently used parameter objects
        network_dataset_param = parameters[0]
        user_name_param = parameters[4]
        password_param = parameters[5]

        #Add all the network dataset layers from the first data frame in the current map document as the default
        #value for the network datasets parameter
        if not network_dataset_param.valueAsText:
            default_network_dataset = ""
            mxd = arcpy.mapping.MapDocument("CURRENT")
            data_frame = arcpy.mapping.ListDataFrames(mxd)[0]
            for layer in  arcpy.mapping.ListLayers(mxd, "*", data_frame):
                if layer.supports("DATASOURCE"):
                    #Skip layers that cannot be described as they are also not network dataset layers
                    try:
                        nds_desc = arcpy.Describe(layer)
                        layer_type = nds_desc.dataType
                        if layer_type.lower() == "networkdatasetlayer":
                            default_network_dataset = layer.name
                    except Exception as ex:
                        pass 
            if default_network_dataset:
                network_dataset_param.value = default_network_dataset            
        return

    def updateMessages(self, parameters):
        '''Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation.'''

        user_name_param = parameters[4]
        password_param = parameters[5]

        #If not signed in to a portal, username and password parameters are required
        sign_in_token = arcpy.GetSigninToken()
        if not sign_in_token:
            if not user_name_param.value:
                user_name_param.setIDMessage("ERROR", 735, user_name_param.displayName)
            if not password_param.value:
                password_param.setIDMessage("ERROR", 735, password_param.displayName)
        return

    def execute(self, parameters, messages):
        '''The source code of the tool.'''

        tool_parameters = {param.name : param.valueAsText for param in parameters}

        
        publish_routing_services = ut.PublishRoutingServices(**tool_parameters)
        #Make sure overwrite outputs is set to true
        overwrite_output = arcpy.env.overwriteOutput
        arcpy.env.overwriteOutput = True
        try:
            publish_routing_services.execute()
        except arcpy.ExecuteError:
            publish_routing_services.logger.exception("A geoprocessing error occurred. Details have been logged to {}".format(publish_routing_services.logger.logFile))
        except Exception as ex:
            publish_routing_services.logger.exception("A python error occurred. Details have been logged to {}".format(publish_routing_services.logger.logFile))
        finally:
            arcpy.env.overwriteOutput = overwrite_output
            publish_routing_services.cleanup()

        #Set the derived outputs

        derived_output_start_index = 6
        arcpy.SetParameterAsText(derived_output_start_index, publish_routing_services.networkAnalysisMapService)
        arcpy.SetParameterAsText(derived_output_start_index + 1,
                                 publish_routing_services.networkAnalysisUtilitiesGeoprocessingService)
        arcpy.SetParameterAsText(derived_output_start_index + 2,
                                 publish_routing_services.networkAnalysisGeoprocessingService)
        arcpy.SetParameterAsText(derived_output_start_index + 3,
                                 publish_routing_services.networkAnalysisSyncGeoprocessingService)


        
        
            
    
    
    
