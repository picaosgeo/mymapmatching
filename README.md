# mymapmatching
mapmatching sample using mapillary map_matching lib 

mapillaryのmap_matchingライブラリを使ったPostGISによるマップマッチング

# Feature
OpenStreetMapの道路リンクデータを使用し、加古川プローブデータの走行軌跡を解析するサンプルプログラム

# Getting Started

### 事前準備
#### postgreSQLインストール
postgreSQLは11.xを想定しています。
サンプルコード内では下記のユーザー/パスワードを使用しています。
インストール環境に合わせて変更します。
~~~
ユーザー名：postgres
パスワード：merryxmas
~~~

#### データベース作成
サンプルコードの実行用に下記のデータベースを作成します。
~~~
CREATE DATABASE mapmatching
    WITH 
    OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    TABLESPACE = pg_default
    CONNECTION LIMIT = -1;
 ~~~

### OSMデータをダウンロード
加古川市のサンプル範囲の経緯度範囲(134.7641,34.6797,134.9534,34.861)のOSMデータを取得します。  
~~~
wget -q --no-check-certificate --header=\"Content-Type: application/osm3s+xml\" https://overpass-api.de/api/map?bbox=134.7641,34.6797,134.9534,34.861 -O kakogawa.osm
~~~

#### ダウンロードしたOSMデータをデータベースにアップロードします。
~~~
osm2pgrouting.exe -f kakogawa.osm -c <ファイルのあるディレクトリ>/mapconfig.xml --prefix kakogawa_ -d (データベース名) -U (ユーザー名) -W (パスワード) -h (ホスト名) --clean
~~~
mapconfig.xmlはpostgreSQLをインストールした bin ディレクトリにあります。

### 加古川プローブデータ（オープンデータ）をダウンロード
G空間情報センターから、加古川市_公用車走行データ（走行履歴）_2016_1をダウンロードします。

https://www.geospatial.jp/ckan/dataset/kakogawacity-car-data/resource/6686c2da-b47c-4cfc-86e1-b4026b41079c

zipを解凍後のファイルから、probe_kaisen197_2016.csv.csvを使用します。
ファイル名をprobe_kaisen197_2016.csvにリネームします。
csvファイルの先頭に下記ヘッダ行を追加します。
~~~
ID,pdate,latitude,longitude
~~~

### プローブ走行軌跡 CSVデータのpostgreSQLインポート
csvファイルのあるフォルダで、
psql -U postgres mapmatching で postgresql に接続し、インポートのためのテーブルを作成します。
~~~
CREATE TABLE public.probe_kaisen197_2016 (
	csv_id bigserial,
	id varchar NOT NULL,
	pdate timestamp NOT NULL,
	latitude double precision NOT NULL,
	longitude double precision NOT NULL,
	way geometry(POINT, 4326)  NULL,
	CONSTRAINT probe_kaisen197_2016_pkey PRIMARY KEY (csv_id)
);
CREATE INDEX probe_kaisen197_2016_way_idx ON probe_0122 USING gist (way);
~~~

csvをインポートします。
~~~
\copy probe_kaisen197_2016(id,pdate,latitude,longitude) from 'probe_kaisen197_2016.csv' csv header
~~~

wayジオメトリフィールドを更新します。
~~~
UPDATE public.probe_kaisen197_2016 SET way=st_transform(ST_SetSRID(ST_Point(longitude,latitude),4301),4326) ;
~~~
