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
import nas

class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "Toolbox"
        self.alias = "nast"

        # List of tool classes associated with this toolbox
        self.tools = [FindRoutes, GenerateServiceAreas, SolveVehicleRoutingProblem, EditVehicleRoutingProblem,
                      FindClosestFacilities, SolveLocationAllocation, GetTravelModes, GetToolInfo]
         
class FindRoutes(nas.NetworkAnalysisTool):
    '''FindRoutes tool in Route service.'''
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        
        self.label = "FindRoutes"
        self.description = ""
        self.category = "Route"
        self.canRunInBackground = False

        #Call the base class constructor
        super(FindRoutes, self).__init__()

        #Store frequently used tool parameters as instance attributes
        self.SUPPORTING_FILES_FOLDER_PARAM_INDEX = 2
        self.NETWORK_DATASETS_PARAM_INDEX = 3
        self.NETWORK_DATASET_EXTENTS_PARAM_INDEX = 4
        self.ANALYSIS_REGION_PARAM_INDEX = 5
        self.UTURN_POLICY_PARAM_INDEX = 12
        self.HIERARCHY_PARAM_INDEX = 16
        self.RESTRICTIONS_PARAM_INDEX = 17
        self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX = 18
        self.SIMPLIFICATION_TOL_PARAM_INDEX = 20

    def getParameterInfo(self):
        """Define parameter definitions"""
        
        #Get common parameters
        common_parameters = self._initializeCommonParameters()

        #Get directions related parameters
        directions_parameters = self._initializeDirectionsParameters()

        #Stops parameter
        stops_param = arcpy.Parameter("Stops", "Stops",  "Input", "GPFeatureRecordSetLayer", "Required")
        stops_param.value = os.path.join(self.layerFilesFolder,  "RTStops.lyr")

        #Measurement Units parameter
        measurement_units_param = arcpy.Parameter("Measurement_Units", "Measurement Units", "Input", "GPString",
                                                  "Required")
        measurement_units_param.filter.list = [unit.replace(" ", "") for unit in self.MEASUREMENT_UNITS]
        measurement_units_param.value = "Minutes"

        #Reorder stops parameter
        reorder_stops_param = arcpy.Parameter("Reorder_Stops_to_Find_Optimal_Routes",
                                              "Reorder Stops to Find Optimal Routes", "Input", "GPBoolean", "Optional")
        reorder_stops_param.filter.list = ["FIND_BEST_ORDER", "USE_INPUT_ORDER"]
        reorder_stops_param.value = "USE_INPUT_ORDER"

        #Preserve terminal stops parameter
        preserve_terminal_stops_param = arcpy.Parameter("Preserve_Terminal_Stops", "Preserve Terminal Stops", "Input",
                                                        "GPString", "Optional")
        preserve_terminal_stops_param.filter.list = ["Preserve First", "Preserve Last", "Preserve First and Last",
                                                     "Preserve None"]
        preserve_terminal_stops_param.value = "Preserve First"

        #Return to start parameter
        return_to_start_param = arcpy.Parameter("Return_to_Start", "Return to Start", "Input", "GPBoolean", "Optional")
        return_to_start_param.filter.list = ["RETURN", "NO_RETURN"]
        return_to_start_param.value = "NO_RETURN"

        #Use time windows parameter
        use_time_windows_param = arcpy.Parameter("Use_Time_Windows", "Use Time Windows", "Input", "GPBoolean",
                                                 "Optional")
        use_time_windows_param.category = "Advanced Analysis"
        use_time_windows_param.filter.list = ["USE_TIMEWINDOWS", "NO_TIMEWINDOWS"]
        use_time_windows_param.value = "NO_TIMEWINDOWS"

        #Time of Day parameter
        time_of_day_param = common_parameters["Time_of_Day"]
        time_of_day_param.category = ""

        #Time Zone for Time of Day parameter
        time_zone_param = common_parameters["Time_Zone_for_Time_of_Day"]
        time_zone_param.category = ""

        #Route shape parameter
        route_shape_param = arcpy.Parameter("Route_Shape", "Route Shape", "Input", "GPString", "Optional")
        route_shape_param.category = "Output"
        route_shape_param.filter.list = ["True Shape", "Straight Line", "None"]
        route_shape_param.value = "True Shape"

        #Populate route edges parameter
        populate_route_edges_param = arcpy.Parameter("Populate_Route_Edges", "Populate Route Edges", "Input",
                                                     "GPBoolean", "Optional")
        populate_route_edges_param.category = "Output"
        populate_route_edges_param.filter.list = ["ROUTE_EDGES", "NO_ROUTE_EDGES"]
        populate_route_edges_param.value = "NO_ROUTE_EDGES"

        #Populate directions parameter
        populate_directions_param = directions_parameters["Populate_Directions"]
        populate_directions_param.value = "DIRECTIONS"

        #Output routes parameter
        output_routes_param = arcpy.Parameter("Output_Routes", "Output Routes", "Output", "DEFeatureClass", "Derived")
        output_routes_param.symbology = os.path.join(self.layerFilesFolder, "RTRoutes.lyr")

        #Output route edges parameter
        output_route_edges_param = arcpy.Parameter("Output_Route_Edges", "Output Route Edges", "Output",
                                                    "DEFeatureClass", "Derived")
        output_route_edges_param.symbology = os.path.join(self.layerFilesFolder, "RTRouteEdges.lyr")

        #Output directions parameter
        output_directions_param = arcpy.Parameter("Output_Directions", "Output Directions", "Output", "DEFeatureClass",
                                                  "Derived")
        output_directions_param.symbology = os.path.join(self.layerFilesFolder, "RTDirections.lyr")

        #Output stops parameter
        output_stops_param = arcpy.Parameter("Output_Stops", "Output Stops", "Output", "DEFeatureClass", "Derived")
        output_stops_param.symbology = os.path.join(self.layerFilesFolder, "RTStops.lyr")

        params = [stops_param, measurement_units_param, common_parameters["Supporting_Files_Folder"],
                  common_parameters["Network_Datasets"], common_parameters["Network_Dataset_Extents"],
                  common_parameters["Analysis_Region"], reorder_stops_param, preserve_terminal_stops_param,
                  return_to_start_param, use_time_windows_param, time_of_day_param, time_zone_param,
                  common_parameters["UTurn_at_Junctions"], common_parameters["Point_Barriers"],
                  common_parameters["Line_Barriers"], common_parameters["Polygon_Barriers"],
                  common_parameters["Use_Hierarchy"], common_parameters["Restrictions"],
                  common_parameters["Attribute_Parameter_Values"], route_shape_param,
                  common_parameters["Route_Line_Simplification_Tolerance"], populate_route_edges_param,
                  populate_directions_param, directions_parameters["Directions_Language"],
                  directions_parameters["Directions_Distance_Units"], directions_parameters["Directions_Style_Name"],
                  common_parameters["Travel_Mode"], common_parameters["Impedance"],
                  common_parameters["Solve_Succeeded"], output_routes_param, output_route_edges_param,
                  output_directions_param, output_stops_param]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        #Convert the parameter values in the format required by the nas.FindRoutes class
        supporting_files_folder = parameters[self.SUPPORTING_FILES_FOLDER_PARAM_INDEX].valueAsText
        nds_properties_file = os.path.join(supporting_files_folder, self.NETWORK_DATASET_PROPERTIES_FILENAME)
        tool_info_file = os.path.join(supporting_files_folder, self.TOOL_INFO_FILENAME)
        
        tool_params = {
            "Stops": parameters[0].value,
            "Measurement_Units": parameters[1].valueAsText,
            "NDS_Properties_File": nds_properties_file,
            "Network_Datasets": parameters[self.NETWORK_DATASETS_PARAM_INDEX].valueAsText,
            "Network_Dataset_Extents": parameters[self.NETWORK_DATASET_EXTENTS_PARAM_INDEX].valueAsText,
            "Analysis_Region" : parameters[self.ANALYSIS_REGION_PARAM_INDEX].valueAsText,
            "Reorder_Stops_to_Find_Optimal_Routes" : parameters[6].value,
            "Preserve_Terminal_Stops": parameters[7].value,
            "Return_to_Start": parameters[8].value,
            "Use_Time_Windows": parameters[9].value,
            "Time_of_Day": parameters[10].value,
            "Time_Zone_for_Time_of_Day": parameters[11].valueAsText,
            "Uturn_at_Junctions": parameters[self.UTURN_POLICY_PARAM_INDEX].valueAsText,
            "Point_Barriers": parameters[13].value,
            "Line_Barriers": parameters[14].value,
            "Polygon_Barriers": parameters[15].value,
            "Use_Hierarchy": parameters[self.HIERARCHY_PARAM_INDEX].value,
            "Restrictions": parameters[self.RESTRICTIONS_PARAM_INDEX].values,
            "Attribute_Parameter_Values": parameters[self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX].value,
            "Route_Shape": parameters[19].valueAsText,
            "Route_Line_Simplification_Tolerance": parameters[self.SIMPLIFICATION_TOL_PARAM_INDEX].valueAsText,
            "Populate_Route_Edges": parameters[21].value,
            "Populate_Directions": parameters[22].value,
            "Directions_Language": parameters[23].valueAsText,
            "Directions_Distance_Units": parameters[24].valueAsText,
            "Directions_Style_Name": parameters[25].valueAsText,
            "Travel_Mode": parameters[26].valueAsText,
            "Impedance": parameters[27].valueAsText,
            "Service_Capabilities": tool_info_file,

        }

        find_routes = nas.FindRoutes(**tool_params)
        find_routes.execute()

        #Set derived outputs from the tool
        DERIVED_OUTPUT_PARAMETER_START = 28
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START, find_routes.solveSucceeded)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 1, find_routes.outputRoutes)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 2, find_routes.outputRouteEdges)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 3, find_routes.outputDirections)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 4, find_routes.outputStops)

        return

class FindClosestFacilities(nas.NetworkAnalysisTool):
    '''FindClosestFacilities tool in ClosestFacility service.'''

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        
        self.label = "FindClosestFacilities"
        self.description = ""
        self.category = "ClosestFacility"
        self.canRunInBackground = False

        #Call the base class constructor
        super(FindClosestFacilities, self).__init__()

        #Store frequently used tool parameters as instance attributes
        self.SUPPORTING_FILES_FOLDER_PARAM_INDEX = 3
        self.NETWORK_DATASETS_PARAM_INDEX = 4
        self.NETWORK_DATASET_EXTENTS_PARAM_INDEX = 5
        self.ANALYSIS_REGION_PARAM_INDEX = 6
        self.HIERARCHY_PARAM_INDEX = 10
        self.UTURN_POLICY_PARAM_INDEX = 13
        self.RESTRICTIONS_PARAM_INDEX = 17
        self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX = 18
        self.SIMPLIFICATION_TOL_PARAM_INDEX = 20

    def getParameterInfo(self):
        """Define parameter definitions"""
        
        #Get common parameters
        common_parameters = self._initializeCommonParameters()

        #Get directions related parameters
        directions_parameters = self._initializeDirectionsParameters()

        #Incidents parameter
        incidents_param = arcpy.Parameter("Incidents", "Incidents",  "Input", "GPFeatureRecordSetLayer", "Required")
        incidents_param.value = os.path.join(self.layerFilesFolder,  "CFIncidents.lyr")

        #Facilities parameter
        facilities_param = arcpy.Parameter("Facilities", "Facilities",  "Input", "GPFeatureRecordSetLayer", "Required")
        facilities_param.value = os.path.join(self.layerFilesFolder,  "CFFacilities.lyr")

        #Measurement Units parameter
        measurement_units_param = arcpy.Parameter("Measurement_Units", "Measurement Units", "Input", "GPString",
                                                  "Required")
        measurement_units_param.filter.list = self.MEASUREMENT_UNITS
        measurement_units_param.value = "Minutes"

        #Number of Facilities to Find parameter
        number_of_facilities_param = arcpy.Parameter("Number_of_Facilities_to_Find", "Number of Facilities to Find",
                                                     "Input", "GPLong", "Optional")
        number_of_facilities_param.value = 1

        #Cutoff parameter
        cutoff_param = arcpy.Parameter("Cutoff", "Cutoff", "Input", "GPDouble", "Optional")

        #Travel Direction parameter
        travel_direction_param = arcpy.Parameter("Travel_Direction", "Travel Direction", "Input", "GPString",
                                                 "Optional")
        travel_direction_param.category = "Advanced Analysis"
        travel_direction_param.filter.list = ["Incident to Facility", "Facility to Incident"]
        travel_direction_param.value = "Incident to Facility"

        #Time of Day Usage parameter
        time_of_day_usage_param = arcpy.Parameter("Time_of_Day_Usage", "Time of Day Usage", "Input", "GPString",
                                                  "Optional")
        time_of_day_usage_param.category = "Advanced Analysis"
        time_of_day_usage_param.filter.list = ["Start Time", "End Time"]
        time_of_day_usage_param.value = "Start Time"

        #Route shape parameter
        route_shape_param = arcpy.Parameter("Route_Shape", "Route Shape", "Input", "GPString", "Optional")
        route_shape_param.category = "Output"
        route_shape_param.filter.list = ["True Shape", "Straight Line", "None"]
        route_shape_param.value = "True Shape"
        
        #Output routes parameter
        output_routes_param = arcpy.Parameter("Output_Routes", "Output Routes", "Output", "DEFeatureClass", "Derived")
        output_routes_param.symbology = os.path.join(self.layerFilesFolder, "CFRoutes.lyr")

        #Output directions parameter
        output_directions_param = arcpy.Parameter("Output_Directions", "Output Directions", "Output", "DEFeatureClass",
                                                  "Derived")
        output_directions_param.symbology = os.path.join(self.layerFilesFolder, "CFDirections.lyr")

        #Output Closest Facilities parameter
        output_facilities_param = arcpy.Parameter("Output_Closest_Facilities", "Output Closest Facilities", "Output",
                                                  "DEFeatureClass", "Derived")
        output_facilities_param.symbology = os.path.join(self.layerFilesFolder, "CFFacilities.lyr")

        params = [incidents_param, facilities_param, measurement_units_param, 
                  common_parameters["Supporting_Files_Folder"], common_parameters["Network_Datasets"],
                  common_parameters["Network_Dataset_Extents"], common_parameters["Analysis_Region"],
                  number_of_facilities_param, cutoff_param, travel_direction_param,
                  common_parameters["Use_Hierarchy"], common_parameters["Time_of_Day"], time_of_day_usage_param,
                  common_parameters["UTurn_at_Junctions"], common_parameters["Point_Barriers"],
                  common_parameters["Line_Barriers"], common_parameters["Polygon_Barriers"],
                  common_parameters["Restrictions"], common_parameters["Attribute_Parameter_Values"], route_shape_param,
                  common_parameters["Route_Line_Simplification_Tolerance"],
                  directions_parameters["Populate_Directions"], directions_parameters["Directions_Language"],
                  directions_parameters["Directions_Distance_Units"], directions_parameters["Directions_Style_Name"],
                  common_parameters["Time_Zone_for_Time_of_Day"], common_parameters["Travel_Mode"],
                  common_parameters["Impedance"], output_routes_param, output_directions_param,
                  common_parameters["Solve_Succeeded"], output_facilities_param]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        #Convert the parameter values in the format required by the nas.FindRoutes class
        supporting_files_folder = parameters[self.SUPPORTING_FILES_FOLDER_PARAM_INDEX].valueAsText
        nds_properties_file = os.path.join(supporting_files_folder, self.NETWORK_DATASET_PROPERTIES_FILENAME)
        tool_info_file = os.path.join(supporting_files_folder, self.TOOL_INFO_FILENAME)
        
        tool_params = {
            "Incidents": parameters[0].value,
            "Facilities": parameters[1].value,
            "Measurement_Units": parameters[2].valueAsText,
            "NDS_Properties_File": nds_properties_file,
            "Network_Datasets": parameters[self.NETWORK_DATASETS_PARAM_INDEX].valueAsText,
            "Network_Dataset_Extents": parameters[self.NETWORK_DATASET_EXTENTS_PARAM_INDEX].valueAsText,
            "Analysis_Region" : parameters[self.ANALYSIS_REGION_PARAM_INDEX].valueAsText,
            "Number_of_Facilities_to_Find" : parameters[7].value,
            "Cutoff": parameters[8].valueAsText,
            "Travel_Direction": parameters[9].valueAsText,
            "Use_Hierarchy": parameters[self.HIERARCHY_PARAM_INDEX].value,
            "Time_of_Day": parameters[11].value,
            "Time_of_Day_Usage": parameters[12].valueAsText,
            "Uturn_at_Junctions": parameters[self.UTURN_POLICY_PARAM_INDEX].valueAsText,
            "Point_Barriers": parameters[14].value,
            "Line_Barriers": parameters[15].value,
            "Polygon_Barriers": parameters[16].value,
            "Restrictions": parameters[self.RESTRICTIONS_PARAM_INDEX].values,
            "Attribute_Parameter_Values": parameters[self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX].value,
            "Route_Shape": parameters[19].valueAsText,
            "Route_Line_Simplification_Tolerance": parameters[self.SIMPLIFICATION_TOL_PARAM_INDEX].valueAsText,
            "Populate_Directions": parameters[21].value,
            "Directions_Language": parameters[22].valueAsText,
            "Directions_Distance_Units": parameters[23].valueAsText,
            "Directions_Style_Name": parameters[24].valueAsText,
            "Time_Zone_for_Time_of_Day": parameters[25].valueAsText,
            "Travel_Mode": parameters[26].valueAsText,
            "Impedance": parameters[27].valueAsText,
            "Service_Capabilities": tool_info_file,
        }

        find_closest_facilities = nas.FindClosestFacilities(**tool_params)
        find_closest_facilities.execute()

        #Set derived outputs from the tool
        DERIVED_OUTPUT_PARAMETER_START = 28
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START, find_closest_facilities.outputRoutes)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 1, find_closest_facilities.outputDirections)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 2, find_closest_facilities.solveSucceeded)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 3, find_closest_facilities.outputFacilities)

        return
    
class GenerateServiceAreas(nas.NetworkAnalysisTool):
    '''GenerateServiceAreas tool in ServiceAreas service.'''

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        
        self.label = "GenerateServiceAreas"
        self.description = ""
        self.category = "ServiceAreas"
        self.canRunInBackground = False

        #Call the base class constructor
        super(GenerateServiceAreas, self).__init__()

        #Set index number for commonly used parameters
        self.SUPPORTING_FILES_FOLDER_PARAM_INDEX = 3
        self.NETWORK_DATASETS_PARAM_INDEX = 4
        self.NETWORK_DATASET_EXTENTS_PARAM_INDEX = 5
        self.ANALYSIS_REGION_PARAM_INDEX = 6
        self.HIERARCHY_PARAM_INDEX = 9
        self.UTURN_POLICY_PARAM_INDEX = 10
        self.SIMPLIFICATION_TOL_PARAM_INDEX = 15
        self.RESTRICTIONS_PARAM_INDEX = 19
        self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX = 20 

    def getParameterInfo(self):
        """Define parameter definitions"""

        #Get common parameters
        common_parameters = self._initializeCommonParameters()

        #Facilities parameter
        facilities_param = arcpy.Parameter("Facilities", "Facilities", "Input", "GPFeatureRecordSetLayer", "Required")
        facilities_param.value = os.path.join(self.layerFilesFolder,  "ServiceAreaFacilities.lyr")

        #Break Values parameter
        break_values_param = arcpy.Parameter("Break_Values", "Break Values", "Input", "GPString", "Required")
        break_values_param.value = "5 10 15"

        #Break Units parameter
        break_units_param = arcpy.Parameter("Break_Units", "Break Units", "Input", "GPString", "Required")
        break_units_param.filter.list = self.MEASUREMENT_UNITS
        break_units_param.value = "Minutes"

        #Travel Direction parameter
        travel_direction_param = arcpy.Parameter("Travel_Direction", "Travel Direction", "Input", "GPString",
                                                 "Optional")
        travel_direction_param.category = "Advanced Analysis"
        travel_direction_param.filter.list = ["Away From Facility", "Towards Facility"]
        travel_direction_param.value = "Away From Facility"

        #Polygons for Multiple Facilities parameter
        polygon_type_param = arcpy.Parameter("Polygons_for_Multiple_Facilities", "Polygons for Multiple Facilities",
                                       "Input", "GPString", "Optional")
        polygon_type_param.category = "Output"
        polygon_type_param.filter.list = ["Overlapping", "Not Overlapping", "Merge by Break Value"]
        polygon_type_param.value = "Overlapping"

        #Polygon Overlap Type parameter
        overlap_type_param = arcpy.Parameter("Polygon_Overlap_Type","Polygon Overlap Type", "Input", "GPString",
                                             "Optional")
        overlap_type_param.category = "Output"
        overlap_type_param.filter.list = ["Rings", "Disks"]
        overlap_type_param.value = "Rings" 

        #Detailed Polygons parameter
        detailed_polygons_param = arcpy.Parameter("Detailed_Polygons", "Detailed Polygons", "Input", "GPBoolean",
                                                  "Optional")
        detailed_polygons_param.category = "Output"
        detailed_polygons_param.filter.list = ["DETAILED_POLYS", "SIMPLE_POLYS"]
        detailed_polygons_param.value = "SIMPLE_POLYS"

        #Polygon Trim Distance parameter
        trim_distance_param = arcpy.Parameter("Polygon_Trim_Distance", "Polygon Trim Distance", "Input",
                                              "GPLinearUnit", "Optional")
        trim_distance_param.category = "Output"
        trim_distance_param.value = "100 Meters"

        #Polygon Simplification Tolerance
        simplification_tol_param = common_parameters["Route_Line_Simplification_Tolerance"]
        simplification_tol_param.name = "Polygon_Simplification_Tolerance"
        simplification_tol_param.displayName = "Polygon Simplification Tolerance"
        
        #Point Barriers parameter
        point_barriers_param = common_parameters["Point_Barriers"]
        point_barriers_param.value = os.path.join(self.layerFilesFolder, "PointBarriers.lyr")

        #Polygon Barriers parameter
        polygon_barriers_param = common_parameters["Polygon_Barriers"]
        polygon_barriers_param.value = os.path.join(self.layerFilesFolder, "PolygonBarriers.lyr")

        #Output Service Areas parameter
        service_areas_param = arcpy.Parameter("Service_Areas", "Service Areas", "Output", "DEFeatureClass", "Required")
        service_areas_param.symbology = os.path.join(self.layerFilesFolder, "ServiceAreas.lyr")
        service_areas_param.value = os.path.join("in_memory", "ServiceAreas")
        
        params = [facilities_param, break_values_param, break_units_param, common_parameters["Supporting_Files_Folder"], 
                  common_parameters["Network_Datasets"], common_parameters["Network_Dataset_Extents"],
                  common_parameters["Analysis_Region"], travel_direction_param, common_parameters["Time_of_Day"],
                  common_parameters["Use_Hierarchy"], common_parameters["UTurn_at_Junctions"], polygon_type_param,
                  overlap_type_param, detailed_polygons_param, trim_distance_param, simplification_tol_param,
                  point_barriers_param, common_parameters["Line_Barriers"], polygon_barriers_param,
                  common_parameters["Restrictions"], common_parameters["Attribute_Parameter_Values"],
                  common_parameters["Time_Zone_for_Time_of_Day"], common_parameters["Travel_Mode"],
                  common_parameters["Impedance"], service_areas_param, common_parameters["Solve_Succeeded"]
                  ]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        #Convert the parameter values in the format required by the nas.FindRoutes class
        supporting_files_folder = parameters[self.SUPPORTING_FILES_FOLDER_PARAM_INDEX].valueAsText
        nds_properties_file = os.path.join(supporting_files_folder, self.NETWORK_DATASET_PROPERTIES_FILENAME)
        tool_info_file = os.path.join(supporting_files_folder, self.TOOL_INFO_FILENAME)
        
        tool_params = {
            "Facilities": parameters[0].value,
            "Break_Values": parameters[1].valueAsText,
            "Measurement_Units": parameters[2].valueAsText,
            "NDS_Properties_File": nds_properties_file,
            "Network_Datasets": parameters[self.NETWORK_DATASETS_PARAM_INDEX].valueAsText,
            "Network_Dataset_Extents": parameters[self.NETWORK_DATASET_EXTENTS_PARAM_INDEX].valueAsText,
            "Analysis_Region" : parameters[self.ANALYSIS_REGION_PARAM_INDEX].valueAsText,
            "Travel_Direction" : parameters[7].valueAsText,
            "Time_of_Day": parameters[8].value,
            "Use_Hierarchy": parameters[self.HIERARCHY_PARAM_INDEX].value,
            "Uturn_at_Junctions": parameters[self.UTURN_POLICY_PARAM_INDEX].valueAsText,
            "Polygons_for_Multiple_Facilities": parameters[11].valueAsText,
            "Polygon_Overlap_Type": parameters[12].valueAsText,
            "Detailed_Polygons": parameters[13].value,
            "Polygon_Trim_Distance": parameters[14].valueAsText,
            "Polygon_Simplification_Tolerance": parameters[self.SIMPLIFICATION_TOL_PARAM_INDEX].valueAsText,
            "Point_Barriers": parameters[16].value,
            "Line_Barriers": parameters[17].value,
            "Polygon_Barriers": parameters[18].value,
            "Restrictions": parameters[self.RESTRICTIONS_PARAM_INDEX].values,
            "Attribute_Parameter_Values": parameters[self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX].value,
            "Time_Zone_for_Time_of_Day": parameters[21].valueAsText,
            "Travel_Mode": parameters[22].valueAsText,
            "Impedance": parameters[23].valueAsText,
            "Service_Areas": parameters[24].valueAsText,
            "Service_Capabilities": tool_info_file,
        }

        generate_service_areas = nas.GenerateServiceAreas(**tool_params)
        generate_service_areas.execute()

        #Set derived outputs from the tool
        DERIVED_OUTPUT_PARAMETER_START = 24
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START, generate_service_areas.outputServiceAreas)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 1, generate_service_areas.solveSucceeded)

class SolveVehicleRoutingProblem(nas.NetworkAnalysisTool):
    '''SolveVehicleRoutingProblem tool in the VehicleRoutingProblem service'''

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        
        self.label = "SolveVehicleRoutingProblem"
        self.description = ""
        self.category = "VehicleRoutingProblem"
        self.canRunInBackground = False

        #Call the base class constructor
        super(SolveVehicleRoutingProblem, self).__init__()

        #Set index number for commonly used parameters
        self.SUPPORTING_FILES_FOLDER_PARAM_INDEX = 6
        self.NETWORK_DATASETS_PARAM_INDEX = 7
        self.NETWORK_DATASET_EXTENTS_PARAM_INDEX = 8
        self.ANALYSIS_REGION_PARAM_INDEX = 9
        self.UTURN_POLICY_PARAM_INDEX = 11
        self.HIERARCHY_PARAM_INDEX = 21
        self.RESTRICTIONS_PARAM_INDEX = 22
        self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX = 23
        self.SIMPLIFICATION_TOL_PARAM_INDEX = 25

        self.toolExecutionClass = nas.SolveVehicleRoutingProblem
         
    def getParameterInfo(self):
        """Define parameter definitions"""

        #Get common parameters and lower case their names
        common_parameters_copy = self._initializeCommonParameters()
        common_parameters = {}
        for name in common_parameters_copy:
            common_param = common_parameters_copy[name]
            common_param.name = common_param.name.lower()
            common_parameters[name.lower()] = common_param

        #Get directions parameters and lower case their names
        directions_parameters_copy = self._initializeDirectionsParameters()
        directions_parameters = {}
        for name in directions_parameters_copy:
            directions_param = directions_parameters_copy[name]
            directions_param.name = directions_param.name.lower()
            directions_parameters[name.lower()] = directions_param

        #Orders parameter
        orders_param = arcpy.Parameter("orders", "Orders", "Input", "GPFeatureRecordSetLayer", "Required")
        orders_param.value = os.path.join(self.layerFilesFolder, "Orders.lyr")

        #Depots parameter
        depots_param = arcpy.Parameter("depots", "Depots", "Input", "GPFeatureRecordSetLayer", "Required")
        depots_param.value = os.path.join(self.layerFilesFolder, "Depots.lyr")

        #Routes parameter
        routes_param = arcpy.Parameter("routes", "Routes", "Input", "GPRecordSet", "Required")
        routes_param.value = os.path.join(self.layerFilesFolder, "schema.gdb", "Routes")
        
        #Breaks parameter
        breaks_param = arcpy.Parameter("breaks", "Breaks", "Input", "GPRecordSet", "Required")
        breaks_param.value = os.path.join(self.layerFilesFolder, "schema.gdb", "Breaks")
        
        #Time Units parameter
        time_units_param = arcpy.Parameter("time_units", "Time Units", "Input", "GPString", "Required")
        time_units_param.filter.list = ["Seconds", "Minutes", "Hours", "Days"]
        time_units_param.value = "Minutes"
        
        #Distance Units parameter
        distance_units_param = arcpy.Parameter("distance_units", "Distance Units", "Input", "GPString", "Required")
        distance_units_param.filter.list = ["Meters", "Kilometers", "Feet", "Yards", "Miles", "NauticalMiles"]
        distance_units_param.value = "Miles"
        
        #Default date param
        default_date_param = common_parameters["time_of_day"]
        default_date_param.name = "default_date"
        default_date_param.displayName = "Default Date"
        
        #U-turn at junctions parameter
        uturn_param = arcpy.Parameter("uturn_policy", "UTurn at Junctions", "Input", "GPString", "Optional")
        uturn_param.category = "Custom Travel Mode"
        uturn_param.filter.list = ["ALLOW_UTURNS", "NO_UTURNS", "ALLOW_DEAD_ENDS_ONLY",
                                   "ALLOW_DEAD_ENDS_AND_INTERSECTIONS_ONLY"]
        uturn_param.value = "ALLOW_UTURNS"
        
        #Time window factor parameter
        time_window_factor_param = arcpy.Parameter("time_window_factor", "Time Window Factor", "Input", "GPString",
                                                   "Optional")
        time_window_factor_param.category = "Advanced Analysis"
        time_window_factor_param.filter.list = ["High", "Medium", "Low"]
        time_window_factor_param.value = "Medium"
          
        #Spatially cluster routes parameter
        spatially_cluster_routes_param = arcpy.Parameter("spatially_cluster_routes", "Spatially Cluster Routes",
                                                         "Input", "GPBoolean", "Optional")
        spatially_cluster_routes_param.category = "Advanced Analysis"
        spatially_cluster_routes_param.filter.list = ["CLUSTER", "NO_CLUSTER"]
        spatially_cluster_routes_param.value = "CLUSTER"

        #Route zones parameter
        route_zones_param = arcpy.Parameter("route_zones", "Route Zones", "Input", "GPFeatureRecordSetLayer",
                                            "Optional")
        route_zones_param.category = "Advanced Analysis"
        route_zones_param.value = os.path.join(self.layerFilesFolder, "RouteZones.lyr")

        #Route Renewals parameter
        route_renewals_param = arcpy.Parameter("route_renewals", "Route Renewals", "Input", "GPRecordSet", "Optional")
        route_renewals_param.category = "Advanced Analysis"
        route_renewals_param.value = os.path.join(self.layerFilesFolder, "schema.gdb", "RouteRenewals")

        #Order pairs parameter
        order_pairs_param = arcpy.Parameter("order_pairs", "Order Pairs", "Input", "GPRecordSet", "Optional")
        order_pairs_param.category = "Advanced Analysis"
        order_pairs_param.value = os.path.join(self.layerFilesFolder, "schema.gdb", "OrderPairs")

        #Excess transit factor parameter
        excess_transit_factor_param = arcpy.Parameter("excess_transit_factor", "Excess Transit Factor", "Input",
                                                      "GPString", "Optional")
        excess_transit_factor_param.category = "Advanced Analysis"
        excess_transit_factor_param.filter.list = ["High", "Medium", "Low"]
        excess_transit_factor_param.value = "Medium"

        #Polygon Barriers parameter
        polygon_barriers_param = common_parameters["polygon_barriers"]
        polygon_barriers_param.value = os.path.join(self.layerFilesFolder, "VRPPolygonBarriers.lyr")

        #Use hierarchy parameter
        use_hierarchy_param = common_parameters["use_hierarchy"]
        use_hierarchy_param.name = "use_hierarchy_in_analysis"

        #Populate route lines parameter
        populate_route_lines_param = arcpy.Parameter("populate_route_lines", "Populate Route Lines", "Input",
                                                     "GPBoolean", "Optional")
        populate_route_lines_param.category = "Output"
        populate_route_lines_param.filter.list = ["ROUTE_LINES", "NO_ROUTE_LINES"]
        populate_route_lines_param.value = "ROUTE_LINES"

        #Impedance parameter
        impedance_parameter = common_parameters["impedance"]
        impedance_parameter_filter = impedance_parameter.filter.list
        impedance_parameter_filter.remove("Travel Distance")
        impedance_parameter.filter.list = impedance_parameter_filter

        #Output unassigned stops parameter
        output_unassigned_stops_param = arcpy.Parameter("out_unassigned_stops", "Output Unassigned Stops", "Output",
                                                        "DETable", "Derived")

        #Output stops parameter
        output_stops_param = arcpy.Parameter("out_stops", "Output Stops", "Output", "DETable", "Derived")

        #Output routes parameter
        output_routes_param = arcpy.Parameter("out_routes", "Output Routes", "Output", "DEFeatureClass", "Derived")
        output_routes_param.symbology = os.path.join(self.layerFilesFolder, "VRPRoutes.lyr")

        #Output directions parameter
        output_directions_param = arcpy.Parameter("out_directions", "Output Directions", "Output", "DEFeatureClass",
                                                  "Derived")
        output_directions_param.symbology = os.path.join(self.layerFilesFolder, "VRPDirections.lyr")


        params = [orders_param, depots_param, routes_param, breaks_param, time_units_param, distance_units_param,
                  common_parameters["supporting_files_folder"], common_parameters["network_datasets"],  
                  common_parameters["network_dataset_extents"], common_parameters["analysis_region"],
                  default_date_param, uturn_param, time_window_factor_param, spatially_cluster_routes_param,
                  route_zones_param, route_renewals_param, order_pairs_param, excess_transit_factor_param,
                  common_parameters["point_barriers"], common_parameters["line_barriers"],
                  polygon_barriers_param, use_hierarchy_param, common_parameters["restrictions"],
                  common_parameters["attribute_parameter_values"], populate_route_lines_param,
                  common_parameters["route_line_simplification_tolerance"],
                  directions_parameters["populate_directions"], directions_parameters["directions_language"], 
                  directions_parameters["directions_style_name"], common_parameters["travel_mode"],
                  impedance_parameter, output_unassigned_stops_param, output_stops_param, output_routes_param,
                  output_directions_param, common_parameters["solve_succeeded"]
                  ]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        #Convert the parameter values in the format required by the nas.SolveVehicleRoutingProblem class
        supporting_files_folder = parameters[self.SUPPORTING_FILES_FOLDER_PARAM_INDEX].valueAsText
        nds_properties_file = os.path.join(supporting_files_folder, self.NETWORK_DATASET_PROPERTIES_FILENAME)
        tool_info_file = os.path.join(supporting_files_folder, self.TOOL_INFO_FILENAME)
        
        tool_params = {
            "Orders": parameters[0].value,
            "Depots": parameters[1].value,
            "Routes": parameters[2].value,
            "Breaks": parameters[3].value,
            "Time_Units": parameters[4].valueAsText,
            "Distance_Units": parameters[5].valueAsText,
            "NDS_Properties_File": nds_properties_file,
            "Network_Datasets": parameters[self.NETWORK_DATASETS_PARAM_INDEX].valueAsText,
            "Network_Dataset_Extents": parameters[self.NETWORK_DATASET_EXTENTS_PARAM_INDEX].valueAsText,
            "Analysis_Region" : parameters[self.ANALYSIS_REGION_PARAM_INDEX].valueAsText,
            "Time_of_Day": parameters[10].value,
            "Uturn_at_Junctions": parameters[self.UTURN_POLICY_PARAM_INDEX].valueAsText,
            "Time_Window_Factor": parameters[12].valueAsText,
            "Spatially_Cluster_Routes": parameters[13].value,
            "Route_Zones": parameters[14].value,
            "Route_Renewals": parameters[15].value,
            "Order_Pairs": parameters[16].value,
            "Excess_Transit_Factor": parameters[17].valueAsText,
            "Point_Barriers": parameters[18].value,
            "Line_Barriers": parameters[19].value,
            "Polygon_Barriers": parameters[20].value,
            "Use_Hierarchy": parameters[self.HIERARCHY_PARAM_INDEX].value,
            "Restrictions": parameters[self.RESTRICTIONS_PARAM_INDEX].values,
            "Attribute_Parameter_Values": parameters[self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX].value,
            "Populate_Route_Lines": parameters[24].value,
            "Route_Line_Simplification_Tolerance": parameters[self.SIMPLIFICATION_TOL_PARAM_INDEX].valueAsText,
            "Populate_Directions": parameters[26].value,
            "Directions_Language": parameters[27].valueAsText,
            "Directions_Style_Name": parameters[28].valueAsText,
            "Travel_Mode": parameters[29].valueAsText,
            "Impedance": parameters[30].valueAsText,
            "Service_Capabilities": tool_info_file,
        }

        solve_vrp = self.toolExecutionClass(**tool_params)
        solve_vrp.execute()

        #Set derived outputs from the tool
        DERIVED_OUTPUT_PARAMETER_START = 31
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START, solve_vrp.outputUnassignedStops)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 1, solve_vrp.outputStops)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 2, solve_vrp.outputRoutes)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 3, solve_vrp.outputDirections)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 4, solve_vrp.solveSucceeded)

        return

class EditVehicleRoutingProblem(SolveVehicleRoutingProblem):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""

        #Call the base class constructor
        super(EditVehicleRoutingProblem, self).__init__()
        
        #Overwrite instance attributes from base class
        self.label = "EditVehicleRoutingProblem"
        self.category = "VehicleRoutingProblemSync"
        self.toolExecutionClass = nas.EditVehicleRoutingProblem

    def getParameterInfo(self):
        """Define parameter definitions"""

        #Same as base class
        return super(EditVehicleRoutingProblem, self).getParameterInfo()

class SolveLocationAllocation(nas.NetworkAnalysisTool):
    '''SolveLocationAllocation tool in LocationAllocation service'''

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        
        self.label = "SolveLocationAllocation"
        self.description = ""
        self.category = "LocationAllocation"
        self.canRunInBackground = False

        #Call the base class constructor
        super(SolveLocationAllocation, self).__init__()

        #Store frequently used tool parameters as instance attributes
        self.SUPPORTING_FILES_FOLDER_PARAM_INDEX = 3
        self.NETWORK_DATASETS_PARAM_INDEX = 4
        self.NETWORK_DATASET_EXTENTS_PARAM_INDEX = 5
        self.ANALYSIS_REGION_PARAM_INDEX = 6
        self.UTURN_POLICY_PARAM_INDEX = 17
        self.HIERARCHY_PARAM_INDEX = 21
        self.RESTRICTIONS_PARAM_INDEX = 22
        self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX = 23
        self.SIMPLIFICATION_TOL_PARAM_INDEX = -1

    def getParameterInfo(self):
        """Define parameter definitions"""
        
        #Get common parameters
        common_parameters = self._initializeCommonParameters()

        #Facilities parameter
        facilities_param = arcpy.Parameter("Facilities", "Facilities",  "Input", "GPFeatureRecordSetLayer", "Required")
        facilities_param.value = os.path.join(self.layerFilesFolder,  "LAFacilities.lyr")

        #Demand Points parameter
        demand_points_param = arcpy.Parameter("Demand_Points", "Demand Points",  "Input", "GPFeatureRecordSetLayer",
                                          "Required")
        demand_points_param.value = os.path.join(self.layerFilesFolder,  "LADemandPoints.lyr")

        #Measurement Units parameter
        measurement_units_param = arcpy.Parameter("Measurement_Units", "Measurement Units", "Input", "GPString",
                                                  "Required")
        measurement_units_param.filter.list = [unit.replace(" ", "") for unit in self.MEASUREMENT_UNITS]
        measurement_units_param.value = "Minutes"

        #Problem Type parameter
        problem_type_param = arcpy.Parameter("Problem_Type", "Problem Type", "Input", "GPString", "Optional")
        problem_type_param.category = "Location-Allocation Problem Settings"
        problem_type_param.filter.list = ["Maximize Attendance", "Maximize Capacitated Coverage", "Maximize Coverage",
                                          "Maximize Market Share", "Minimize Facilities", "Minimize Impedance",
                                          "Target Market Share"]
        problem_type_param.value = "Minimize Impedance"

        #Number of Facilities to Find parameter
        number_of_facilities_param = arcpy.Parameter("Number_of_Facilities_to_Find", "Number of Facilities to Find",
                                                     "Input", "GPLong", "Optional")
        number_of_facilities_param.category = "Location-Allocation Problem Settings"
        number_of_facilities_param.value = 1

        #Default Measurement Cutoff parameter
        default_cutoff_param = arcpy.Parameter("Default_Measurement_Cutoff", "Default Measurement Cutoff", "Input",
                                       "GPDouble", "Optional")
        default_cutoff_param.category = "Location-Allocation Problem Settings"

        #Default Capacity parameter
        default_capacity_param = arcpy.Parameter("Default_Capacity", "Default Capacity", "Input", "GPDouble",
                                                 "Optional")
        default_capacity_param.category = "Location-Allocation Problem Settings"
        default_capacity_param.value = 1

        #Target Market Share parameter
        target_market_share_param = arcpy.Parameter("Target_Market_Share", "Target Market Share", "Input", "GPDouble",
                                                    "Optional")
        target_market_share_param.category = "Location-Allocation Problem Settings"
        target_market_share_param.value = 10

        #Measurement Transformation Model parameter
        transformation_model_param = arcpy.Parameter("Measurement_Transformation_Model",
                                                     "Measurement Transformation Model", "Input", "GPString",
                                                     "Optional")
        transformation_model_param.category = "Location-Allocation Problem Settings"
        transformation_model_param.filter.list = ["Linear", "Power", "Exponential"]
        transformation_model_param.value = "Linear"

        #Measurement Transformation Factor parameter
        transformation_factor_param = arcpy.Parameter("Measurement_Transformation_Factor",
                                                      "Measurement Transformation Factor", "Input", "GPDouble",
                                                      "Optional")
        transformation_factor_param.category = "Location-Allocation Problem Settings"
        transformation_factor_param.value = 1


        #Travel Direction parameter
        travel_direction_param = arcpy.Parameter("Travel_Direction", "Travel Direction", "Input", "GPString",
                                                 "Optional")
        travel_direction_param.category = "Advanced Analysis"
        travel_direction_param.filter.list = ["Demand to Facility", "Facility to Demand"]
        travel_direction_param.value = "Facility to Demand"

        #Allocation Line Shape parameter
        line_shape_param = arcpy.Parameter("Allocation_Line_Shape", "Allocation Line Shape", "Input", "GPString",
                                            "Optional")
        line_shape_param.category = "Output"
        line_shape_param.filter.list = ["None", "Straight Line"]
        line_shape_param.value = "Straight Line"
        
        #Output routes parameter
        output_lines_param = arcpy.Parameter("Output_Allocation_Lines", "Output Allocation Lines", "Output", 
                                              "DEFeatureClass", "Derived")
        output_lines_param.symbology = os.path.join(self.layerFilesFolder, "AllocationLines.lyr")

        #Output Facilities parameter
        output_facilities_param = arcpy.Parameter("Output_Facilities", "Output Facilities", "Output",
                                                  "DEFeatureClass", "Derived")
        output_facilities_param.symbology = os.path.join(self.layerFilesFolder, "LAOutputFacilities.lyr")

        #Output Demand Points parameter
        output_demand_points_param = arcpy.Parameter("Output_Demand_Points", "Output Demand Points", "Output",
                                                     "DEFeatureClass", "Derived")
        output_demand_points_param.symbology = os.path.join(self.layerFilesFolder, "LAOutputDemandPoints.lyr")

        params = [facilities_param, demand_points_param, measurement_units_param, 
                  common_parameters["Supporting_Files_Folder"], common_parameters["Network_Datasets"],
                  common_parameters["Network_Dataset_Extents"], common_parameters["Analysis_Region"],
                  problem_type_param,  number_of_facilities_param, default_cutoff_param, default_capacity_param,
                  target_market_share_param, transformation_model_param, transformation_factor_param,
                  travel_direction_param, common_parameters["Time_of_Day"],
                  common_parameters["Time_Zone_for_Time_of_Day"], common_parameters["UTurn_at_Junctions"],
                  common_parameters["Point_Barriers"], common_parameters["Line_Barriers"],
                  common_parameters["Polygon_Barriers"], common_parameters["Use_Hierarchy"],
                  common_parameters["Restrictions"], common_parameters["Attribute_Parameter_Values"], line_shape_param,
                  common_parameters["Travel_Mode"], common_parameters["Impedance"], 
                  common_parameters["Solve_Succeeded"], output_lines_param, output_facilities_param, 
                  output_demand_points_param]

        return params

    def execute(self, parameters, messages):
        """The source code of the tool."""

        #Convert the parameter values in the format required by the nas.FindRoutes class
        supporting_files_folder = parameters[self.SUPPORTING_FILES_FOLDER_PARAM_INDEX].valueAsText
        nds_properties_file = os.path.join(supporting_files_folder, self.NETWORK_DATASET_PROPERTIES_FILENAME)
        tool_info_file = os.path.join(supporting_files_folder, self.TOOL_INFO_FILENAME)
        
        tool_params = {
            "Facilities": parameters[0].value,
            "Demand_Points": parameters[1].value,
            "Measurement_Units": parameters[2].valueAsText,
            "NDS_Properties_File": nds_properties_file,
            "Network_Datasets": parameters[self.NETWORK_DATASETS_PARAM_INDEX].valueAsText,
            "Network_Dataset_Extents": parameters[self.NETWORK_DATASET_EXTENTS_PARAM_INDEX].valueAsText,
            "Analysis_Region" : parameters[self.ANALYSIS_REGION_PARAM_INDEX].valueAsText,
            "Problem_Type": parameters[7].valueAsText,
            "Number_of_Facilities_to_Find" : parameters[8].value,
            "Default_Measurement_Cutoff": parameters[9].valueAsText,
            "Default_Capacity": parameters[10].value,
            "Target_Market_Share": parameters[11].value,
            "Measurement_Transformation_Model": parameters[12].valueAsText,
            "Measurement_Transformation_Factor": parameters[13].value,
            "Travel_Direction": parameters[14].valueAsText,
            "Time_of_Day": parameters[15].value,
            "Time_Zone_for_Time_of_Day": parameters[16].valueAsText,
            "Uturn_at_Junctions": parameters[self.UTURN_POLICY_PARAM_INDEX].valueAsText,
            "Point_Barriers": parameters[18].value,
            "Line_Barriers": parameters[19].value,
            "Polygon_Barriers": parameters[20].value,
            "Use_Hierarchy": parameters[self.HIERARCHY_PARAM_INDEX].value,
            "Restrictions": parameters[self.RESTRICTIONS_PARAM_INDEX].values,
            "Attribute_Parameter_Values": parameters[self.ATTRIBUTE_PARAMETER_VALUES_PARAM_INDEX].value,
            "Allocation_Line_Shape": parameters[24].valueAsText, 
            "Travel_Mode": parameters[25].valueAsText,
            "Impedance": parameters[26].valueAsText,
            "Service_Capabilities": tool_info_file,
        }

        solve_location_allocation = nas.SolveLocationAllocation(**tool_params)
        solve_location_allocation.execute()

        #Set derived outputs from the tool
        DERIVED_OUTPUT_PARAMETER_START = 27
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START, solve_location_allocation.solveSucceeded)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 1, solve_location_allocation.outputAllocationLines)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 2, solve_location_allocation.outputFacilities)
        arcpy.SetParameterAsText(DERIVED_OUTPUT_PARAMETER_START + 3, solve_location_allocation.outputDemandPoints)

        return

class GetTravelModes(object):
    '''GetTravelModes tool in Utilities service.'''

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        
        self.label = "GetTravelModes"
        self.description = "Get a list of travel modes that can be used with directions and routing services available in your portal."
        self.category = "Utilities"
        self.canRunInBackground = False

        #Need to skip validation when running as a GP service
        self.runningOnServer = arcpy.GetInstallInfo().get('ProductName', "").lower() == 'server'
    
    def getParameterInfo(self):
        """Define parameter definitions"""

        #Supporting Files parameter
        supporting_files_param = arcpy.Parameter("supportingFiles", "Supporting Files", "Input", "GPValueTable",
                                                 "Required")
        supporting_files_param.columns = [["DEFile", "Supporting File"], ["GPString", "File Type"]]
        supporting_files_param.filters[0].list = ["json"]
        supporting_files_param.filters[1].type = "ValueList"
        supporting_files_param.filters[1].list = nas.GetTravelModes.FILE_TYPES
        
        #output supported travel modes parameter
        output_travel_modes_param = arcpy.Parameter("supportedTravelModes", "Supported Travel Modes", "Output",
                                                    "DETable", "Derived")

        #output default travel mode parameter
        output_default_travel_mode_param = arcpy.Parameter("defaultTravelMode", "Default Travel Mode", "Output",
                                                           "GPString", "Derived")

        params =[supporting_files_param, output_travel_modes_param, output_default_travel_mode_param]
        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""

        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""

        if self.runningOnServer:
            return

        #Raise an error if default travel modes file is not specified.
        supporting_files_param = parameters[0]
        supporting_files = supporting_files_param.values
        if supporting_files:
            required_file_type = nas.GetTravelModes.FILE_TYPES[1]
            file_types = [file_type for file_path, file_type in supporting_files]
            if not required_file_type in file_types:
                supporting_files_param.setIDMessage("ERROR", 735, required_file_type)
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        tool_params = {
            "supportingFiles": parameters[0].values,
        }

        get_travel_modes = nas.GetTravelModes(**tool_params)
        get_travel_modes.execute()

        #Set derived outputs
        arcpy.SetParameterAsText(1, get_travel_modes.outputTable)
        arcpy.SetParameterAsText(2, get_travel_modes.defaultTravelMode)

class GetToolInfo(object):
    '''GetToolInfo tool in the Utilities service'''


    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        
        self.label = "GetToolInfo"
        self.description = '''Get additional information such as the description of the network dataset used for the
        analysis and execution limits for a tool available in the geoprocessing service.'''
        self.category = "Utilities"
        self.canRunInBackground = False
    
    def getParameterInfo(self):
        """Define parameter definitions"""

        #Supporting Files parameter
        supporting_files_folder_param = arcpy.Parameter("supportingFilesFolder", "Supporting Files Folder", "Input",
                                                        "DEFolder", "Required")

        #Service name parameter
        service_name_param = arcpy.Parameter("serviceName", "Service Name", "Input", "GPString", "Required")
        service_name_param.filter.list = sorted(nas.NetworkAnalysisService.SERVICE_NAMES.keys())
        service_name_param.value = "asyncRoute"

        #Tool name parameter
        tool_name_param = arcpy.Parameter("toolName", "Tool Name", "Input", "GPString", "Required")
        tool_names = [tool for tools in nas.NetworkAnalysisService.SERVICE_NAMES.itervalues() for tool in tools]
        tool_name_param.filter.list = sorted(tool_names)
        tool_name_param.value = "FindRoutes"
        
        #output tool info parameter
        output_tool_info_param = arcpy.Parameter("toolInfo", "Tool Info", "Output", "GPString", "Derived")

        params = [supporting_files_folder_param, service_name_param, tool_name_param, output_tool_info_param]
        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
                
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""

        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        tool_params = {
            "toolInfoFile": os.path.join(parameters[0].valueAsText, nas.NetworkAnalysisTool.TOOL_INFO_FILENAME),
            "serviceName": parameters[1].valueAsText,
            "toolName": parameters[2].valueAsText,
        }

        get_tool_info = nas.GetToolInfo(**tool_params)

        try:
            get_tool_info.execute()
        except Exception as ex:
            arcpy.AddError("A geoprocessing error occurred")

        #Set derived outputs
        arcpy.SetParameterAsText(3, get_tool_info.toolInfo)