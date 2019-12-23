# -*- coding: utf-8 -*-
#con.execute_non_query(INSERT_EX_SQ.encode('your language encoder'))
#

__doc__='''
使い方：
'''


import os
from os import getenv
import sys
import datetime
import time
import locale
import psycopg2
import csv


from map_matching import map_matching as mm
from map_matching.utils import Edge, Measurement

version = u'1.0.0'

viewflg=False
logflg=False

def generate_placeholder(length, width):
    """
    Generate "(%s, %s, %s, ...), ..." for placing parameters.
    """
    return ','.join('(' + ','.join(['%s'] * width) + ')' for _ in range(length))

def create_sequence_subquery(length, columns):
    """Create a subquery for sequence."""
    placeholder = generate_placeholder(length, len(columns))
    subquery = 'WITH sequence {columns} AS (VALUES {placeholder})'.format(
        columns='(' + ','.join(columns) + ')',
        placeholder=placeholder)
    return subquery



def query_edges_in_sequence_bbox(conn, road_table_name, sequence, search_radius):
    
    """
	サーチ円の分拡張されたバウンディングボックス内のシーケンスのすべての道路エッジをクエリーする
    Query all road edges within the bounding box of the sequence
    expanded by search_radius.
    """
    if not sequence:
        return

    #テストのため固定

    stmt = '''
    -- NOTE the length unit is in km
    SELECT edge.gid, edge.source, edge.target, edge.length * 1000, edge.length * 1000
    FROM {road_table_name} AS edge
         CROSS JOIN (SELECT ST_Extent(ST_MakePoint(ST_X({sequence_name}.way), ST_Y({sequence_name}.way)))::geometry AS extent FROM {sequence_name}) AS extent
    WHERE edge.the_geom && ST_Envelope(ST_Buffer(extent.extent::geography, {search_radius})::geometry)
    '''.format(road_table_name=road_table_name,sequence_name=sequence,search_radius=search_radius)


    cur = conn.cursor()
    cur.execute(stmt)

    for gid, source, target, cost, reverse_cost in cur.fetchall():
        edge = Edge(id=gid,
                    start_node=source,
                    end_node=target,
                    cost=cost,
                    reverse_cost=reverse_cost)
        yield edge

    cur.close()

def build_road_network(edges):
    """
	エッジリストの双方向道路グラフデータを構築する
	Construct the bidirectional road graph given a list of edges.
	"""
    graph = {}

    # Graph with bidirectional edges
    for edge in edges:
        graph.setdefault(edge.start_node, []).append(edge)
        graph.setdefault(edge.end_node, []).append(edge.reversed_edge())

    return graph


# Subclass the native Candidate class to support more attributes
class Candidate(mm.Candidate):
    def __init__(self, measurement, edge, location, distance):
        super(Candidate, self).__init__(measurement=measurement, edge=edge, location=location, distance=distance)
        self.lon = None
        self.lat = None
        self.mlon=None
        self.mlat=None
        self.ptime= None
        self.edgeflg=None

def query_candidates(conn, road_table_name, sequence, search_radius):
    """
    サーチ円内に存在するシーケンスデータの各々の計測データの候補をクエリーする
    Query candidates of each measurement in a sequence within
    search_radius.
    """

    stmt = '''
        WITH 
	    --- WITH sequence AS (subquery here),
	    seq AS (SELECT *,
	                   ST_SetSRID(ST_MakePoint(ST_X({sequence_name}.way), ST_Y({sequence_name}.way)), 4326) AS geom,
	                   ST_SetSRID(ST_MakePoint(ST_X({sequence_name}.way), ST_Y({sequence_name}.way)), 4326)::geography AS geog
	        FROM {sequence_name})
	    
	    SELECT seq.csv_id, ST_X(seq.way) as lon, ST_Y(seq.way) as lat, seq.ptime,
	           --- Edge information
	           edge.gid, edge.source, edge.target,
	           edge.length, edge.length,
	
	           --- Location, a float between 0 and 1 representing the location of the closest point on the edge to the measurement.
	           ST_LineLocatePoint(edge.the_geom, seq.geom) AS location,
	
	           --- Distance in meters from the measurement to its candidate's location
	           ST_Distance(seq.geog, edge.the_geom::geography) AS distance,
	
	           --- Candidate's location (a position along the edge)
	           ST_X(ST_ClosestPoint(edge.the_geom, seq.geom)) AS clon,
	           ST_Y(ST_ClosestPoint(edge.the_geom, seq.geom)) AS clat
	
	    FROM seq CROSS JOIN {road_table_name} AS edge
	    WHERE edge.the_geom && ST_Envelope(ST_Buffer(seq.geog, {search_radius})::geometry)
	          AND ST_DWithin(seq.geog, edge.the_geom::geography, {search_radius})
    '''.format(road_table_name=road_table_name,sequence_name=sequence,search_radius=search_radius)

    cur = conn.cursor()
    cur.execute(stmt)

    for mid, mlon, mlat, mdt, \
        eid, source, target, cost, reverse_cost, \
        location, distance, \
        clon, clat in cur:

        measurement = Measurement(id=mid, lon=mlon, lat=mlat)

        edge = Edge(id=eid, start_node=source, end_node=target, cost=cost, reverse_cost=reverse_cost)

        assert 0 <= location <= 1
        candidate = Candidate(measurement=measurement, edge=edge, location=location, distance=distance)

        # Coordinate along the edge (not needed by MM but might be
        # useful info to users)
        candidate.lon = clon    # マッチングポイント X
        candidate.lat = clat    # マッチングポイント Y
        candidate.mlon = mlon   # プローブポイント X
        candidate.mlat = mlat   # プローブポイント Y
        candidate.ptime = mdt    # プローブ日付(TIMESTAMP)
        candidate.edgeflg = 0

        yield candidate

    cur.close()


def map_match(conn, road_table_name,sequence, search_radius, max_route_distance):
    """シーケンステーブルをマッチングし、candidatesリストを返す"""

    start=time.time()

    # Prepare the network graph and the candidates along the sequence
    edges = query_edges_in_sequence_bbox(conn, road_table_name,sequence, search_radius)
    print( 'edges:' ,time.time() - start)
    start=time.time()

    network = build_road_network(edges)
    print('network:', time.time() - start)
    start=time.time()

    candidates = query_candidates(conn, road_table_name, sequence, search_radius)
    print('candidates:', time.time() - start)
    start=time.time()


    # If the route distance between two consive measurements are
    # longer than `max_route_distance` in meters, consider it as a
    # breakage
    matcher = mm.MapMatching(network.get, max_route_distance)
    print( 'matcher:', time.time() - start)


    # Match and return the selected candidates along the path
    return list(matcher.offline_match(candidates))




def main(argv):

	pguser='postgres'
	pgport='5432'
	pghost='localhost'
	pgdbname ='evtest'
	pgpassword='apptec'

	# postgresql://{username}:{password}@{hostname}:{port}/{database}
	dsn='postgresql://{0}:{1}@{2}:{3}/{4}'.format(pguser,pgpassword,pghost,pgport,pgdbname)

	# OSMデータダウンロード指定のファイル名から作成予定のOSMテーブル名を生成
	osmtbl='kakogawa_ways'

	# プローブCSVファイルをアップロードする
	csvtbl='probe_kaisen197_2016'

	# プローブテーブルを使用してマップマッチングを実行する

	start=time.time()
	conn = psycopg2.connect(dsn)
	candidates = map_match(conn, osmtbl,csvtbl, search_radius, max_route_distance)
	conn.close()

	process_time = time.time() - start

	print( 'process_time;',process_time )

	# 候補データに各エッジの最初と最後の識別フラグを追加する
	flg=0
	cb=None

	for candidate in candidates:
		candidate.edgeflg=(0 if flg == candidate.edge.id else 1)
		flg=candidate.edge.id
		if cb is not None :
			if candidate.edgeflg == 1 and cb.edgeflg==0 :
				cb.edgeflg=2
		cb=candidate

	with open( outputcsv, "w" ) as f:
		f.write(u'mid,ptime,mlon,mlat,clon,clat,cid,cloc,cdist,edgeflg\n')
		for candidate in candidates:
			a= \
			'{0},'.format(candidate.measurement.id) +\
			'{0},'.format(candidate.ptime)+\
			'{0:.6f},{1:.6f},'.format(*map(float, (candidate.measurement.lon, candidate.measurement.lat))) +\
			'{0:.6f},{1:.6f},'.format(*map(float, (candidate.lon, candidate.lat)))+\
			'{0},'.format(candidate.edge.id) +\
			'{0:.2f},'.format(candidate.location) +\
			'{0:.2f},'.format(candidate.distance) +\
			'{0}\n'.format(candidate.edgeflg)
			f.write(a)
		f.close()
        


	return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
