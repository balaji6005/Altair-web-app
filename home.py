import dash
import dash_bootstrap_components as dbc
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State, MATCH, ALL
# from dash_html_components.Button import Button
import dash_draggable
import os, uuid, json, requests
import altair as alt
import dash_alternative_viz as dav
from flask_login import current_user
import pandas as pd

from app import app
from functions.connections import mongo_connect
from functions import get_element_from_json, join_list, generate_options_from_list, set_element_in_json
from functions.global_variables import ALTAIR_ENCODING_DATATYPES

from dotenv import load_dotenv
load_dotenv()

client = mongo_connect(os.getenv("MONGO_HOST"),os.getenv("MONGO_PORT"),(os.getenv("MONGO_USERNAME"),os.getenv("MONGO_PASSWORD")))

layout = html.Div(
    style={"margin-left": "20px", "margin-right": "20px"},
    children=[
        dbc.Row([
            dbc.Col([html.Button(id="open-widget",children="Open Widgets",className="btn-primary",)]),
            dbc.Col([html.Button(id="save-dashboard",children="Save Dashboard",className="btn-primary",)], style={"text-align":"right"}),
        ]),
        dbc.Alert(id="dashboard-alert",
            is_open=False,
            duration=4000,
        ),
        dbc.Modal(
            [
                dbc.ModalHeader("Add Widget"),
                dbc.ModalBody([
                    dbc.Row([
                        dbc.Col([dcc.Dropdown(
                            id="widget-select",
                            options=[],
                            value=[],
                            placeholder="Select a Widget"
                        ),]),
                        dbc.Col([dcc.Dropdown(
                            id="dataset-select",
                            options=[],
                            value=[],
                            placeholder="Select a Dataset"
                        )])
                    ]),
                    html.Div([
                        html.Button(id="load-widget-data",children="Load",className="btn-info"),
                    ],style={"text-align":"right","padding":"2%"}),
                    html.Hr(),
                    html.H5("Sample Chart"),
                    dbc.Row([
                        dbc.Col([html.Div(id="sample-widget")], width=6),
                        dbc.Col([
                            html.Div(id="widget-mappings"),
                            html.Button(id="add-widget",children="Add",className="btn-success", style={"float":"right"}),
                        ], width=6)
                    ]),
                ], style={"min-height":"400px"}),
                dbc.ModalFooter(
                    dbc.Button(
                        "Close", id="close-modal", className="ml-auto", n_clicks=0
                    )
                ),
            ],
            id="add-widget-modal",
            scrollable=True,
            size="xl",
            is_open=False,
            style={"max-width":"1440px"}
        ),
        dash_draggable.ResponsiveGridLayout(
            id="main-draggable",
            clearSavedLayout=True,
            layouts={
                "lg": []
            },
            children=[]),
        html.Br(),
    ]
)

@app.callback(
    [Output("add-widget-modal", "is_open"), Output("widget-select","options"), Output("dataset-select","options")],
    [Input("open-widget","n_clicks"), Input("close-modal", "n_clicks")],
    [State("add-widget-modal", "is_open"), State("widget-select","options"), State("dataset-select","options")],
    prevent_initial_call=True
)
def open_widget_modal(n1,n2,is_open,dropdown_options,dataset_options):
    global client
    if n1 or n2:
        db = client['Altair']
        col = db['Widgets']
        widgets = list(col.find({},{"_id":0,"name":1}))
        widgets = [{"label":widget_name['name'],"value":widget_name['name']} for widget_name in widgets]
        col = db['Datasets']
        datasets = col.find_one({"username":current_user.username},{"_id":0,"datasets":1})
        datasets = [{"label":dataset_name,"value":dataset_name} for dataset_name in list(datasets['datasets'].keys())]
        return [not is_open, widgets, datasets]
    return [is_open, dropdown_options, dataset_options]

@app.callback(
    [Output("widget-mappings","children"), Output("sample-widget","children")],
    [Input("load-widget-data","n_clicks")],
    [State("widget-select","value"),State("dataset-select","value")],
    prevent_initial_call=True
)
def load_widget_data(n, widget_name, dataset_name):
    global client
    db = client['Altair']
    col = db['Widgets']
    widget = col.find_one({"name":widget_name},{"_id":0})
    col = db['Datasets']
    datasets = col.find_one({"username":current_user.username},{"_id":0,"datasets":1})
    dataset = datasets['datasets'][dataset_name]
    columns = []
    if dataset['type'] == 'json':
        if dataset['url'].lower().endswith('json'):
            df = pd.read_json(dataset['url'])
        else:
            res = requests.get(dataset['url'])
            df = pd.DataFrame(res.json())
        columns = list(df.columns)
    widget_data = []
    for layer in widget['layers']:
        widget_data.append(html.H5(layer['layer_name']))
        for field in layer['fields']:
            widget_data.append(html.P(field['name']+" : "))
            if field['type'] == 'encoding':
                widget_data.append(
                    dbc.Row([
                        dbc.Col([dcc.Input(id={"type":"widget-mapping","id":join_list(field['title_loc'],".")}, placeholder="Enter Title")]),
                        dbc.Col([dcc.Dropdown(id={"type":"widget-mapping","id":join_list(field['chart_json_field_loc'],".")}, options=generate_options_from_list(columns), placeholder="Select the Column")]),
                        dbc.Col([dcc.Dropdown(id={"type":"widget-mapping","id":join_list(field['chart_json_fieldtype_loc'],".")}, options=generate_options_from_list(list(ALTAIR_ENCODING_DATATYPES.keys())), placeholder="Select the Encoding Type")]),
                    ])
                )
            elif field['type'] == 'title':
                widget_data.append(
                    dbc.Row([
                        dbc.Col([dcc.Input(id={"type":"widget-mapping","id":join_list(field['chart_json_loc'],".")}, placeholder="Enter Title")]),
                    ])
                )
        widget_data.append(html.Hr())
    chart = dav.VegaLite(spec=alt.Chart.from_json(widget['chart_json']).to_dict())
    return [widget_data, chart]

@app.callback(
    [Output("main-draggable","layouts"), Output("main-draggable","children")],
    [Input("add-widget","n_clicks")],
    [
        State({'type':"widget-mapping","id":ALL},"value"),State({'type':"widget-mapping","id":ALL},"id"),
        State("widget-select","value"),State("dataset-select","value"),
        State("main-draggable","layouts"), State("main-draggable","children")
    ],
)
def add_widget(n_clicks, values, ids, widget_name, dataset_name,layouts, children):
    global client
    ctx = dash.callback_context.triggered
    db = client['Altair']
    print(ctx)
    if ctx[0]['prop_id'] != '.':
        col = db['Widgets']
        widget = col.find_one({"name":widget_name},{"_id":0})
        col = db['Datasets']
        datasets = col.find_one({"username":current_user.username},{"_id":0,"datasets":1})
        dataset = datasets['datasets'][dataset_name]
        chart_json = json.loads(widget['chart_json'])
        if dataset['type'] == 'json':
            if dataset['url'].lower().endswith('json'):
                chart_json['data'] = {'url':dataset['url']}
                chart_json.pop("datasets", None)
            else:
                res = requests.get(dataset['url'])
                df = pd.DataFrame(res.json())
                dataset_name = 'data-'+str(uuid.uuid4())
                chart_json['data']={'name':dataset_name}
                chart_json['datasets']={}
                chart_json['datasets'][dataset_name] = df.to_dict(orient='records')
                # chart_json.pop("datasets", None)
        for value, id in zip(values, ids):
            if value:
                print(id)
                set_element_in_json(chart_json, id['id'].split('.'), value)
        print(json.dumps(chart_json, indent=4))
        # chart_id = {"type":"charts","id":str(uuid.uuid4())}
        chart_id = str(uuid.uuid4())
        chart = dav.VegaLite(id=chart_id,spec=alt.Chart.from_json(json.dumps(chart_json)).to_dict())
        if len(layouts['lg'])>0:
            layouts['lg'].append({'i':chart_id,"x":layouts['lg'][-1]["x"]+layouts['lg'][-1]["h"],"y":0,"w":4,"h":4})
        else:
            layouts['lg'].append({'i':chart_id,"x":0,"y":0,"w":4,"h":4})
        print("layouts:", layouts)
        print("children:", children+[chart])
        return [layouts, children+[chart]]
    else:
        col = db['UserDashboards']
        dashboard_data = col.find_one({"username":current_user.username})
        if dashboard_data:
            for chart in dashboard_data['charts']:
                children.append(dav.VegaLite(id=chart["id"],spec=alt.Chart.from_json(chart["spec"]).to_dict()))
            return [dashboard_data['layouts'], children]
        else:
            return [{"lg":[]}, []]

@app.callback(
    [Output("dashboard-alert","children"), Output("dashboard-alert","is_open")],
    [Input("save-dashboard","n_clicks")],
    [
        State("main-draggable","layouts"),
        State("main-draggable","children"),
    ],
    prevent_initial_call=True
)
def save_dashboard(n_clicks, layouts, children):
    global client
    db = client['Altair']
    col = db['UserDashboards']
    dashboard_data = {"username":current_user.username, "location":"/home"}
    print(children[0]['props']['spec'])
    dashboard_data['layouts'] = layouts
    charts = []
    for chart in children:
        charts.append({"id":chart['props']['id'], "spec":json.dumps(chart['props']['spec'])})
    dashboard_data['charts'] = charts
    col.update({"username":current_user.username}, dashboard_data, upsert=True)
    return ["",False]