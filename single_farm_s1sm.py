# -*- coding: utf-8 -*-
"""single_farm_solo_S1SM.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1Y2SYbmC1Ki1ALcHwh6Vh8yFoV81neFoD

# **Install these Packages and restart runtime**
"""

# %pip install geopandas --quiet
# %pip install rtree --quiet
# %pip install pygeos --quiet
# %pip install botocore --quiet
# %pip install boto3 --quiet
# %pip install geemap --quiet
# %pip install pyshp --quiet

"""# **Earth Engine Authentication**"""

#import ee

# Trigger the authentication flow.
# ee.Authenticate()

# Initialize the library.
#ee.Initialize()

"""# **Import Necessary Packages**"""

# Commented out IPython magic to ensure Python compatibility.
import matplotlib.pyplot as plt
import numpy as np
import ee
#import geemap
from IPython.display import clear_output 
from glob import glob
#from google.colab import drive
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from matplotlib import colors
from matplotlib.patches import Patch
import matplotlib as mpl
import os
import io
from PIL import Image
from mpl_toolkits.axes_grid1 import make_axes_locatable
from datetime import datetime, timedelta
import ast
import boto3
import botocore
from botocore.exceptions import ClientError
# %matplotlib notebook
import warnings
warnings.filterwarnings("ignore")

ee.Initialize()

"""# **Generate PNGs for Farm Time Series**


1.   Accessing Farm WKTs from Google Drive
2.   Generating both Earth Engine and Geopandas Polygons

1.   Accessing Earth Engine's 'COPERNICUS/S1_GRD' dataset for a farm
2.   Generating Earth Engine Time Series Image Collection for the farm

1.   Calculating Minimum, Maximum and Sensitivity Raster image from the Image Collection 
2.  Calculating Relative Soil Moisture (RSM) from the 'VV' Band and map the values of RSM on the 'VV' band

1.   Converting the Image Collection to Earth Engine List of Images
2.   Iterating through the list of images, access RSM mapped 'VV' band and convert them into numpy arrays

1.   Plotting the final the Image 
2.   Saving the plots in Bytes format

1.   Writing the saved plots in the AWS folder path
















"""

#from google.colab import drive

#mount = '/content/drive'
#print("Colab: mounting Google drive on ", mount)

#drive.mount(mount, force_remount = True)
#drive_root = mount + "/My Drive/ndviS2Farms/"

"""# **Earth Engine Functions**"""

# # Function for calculating Relative Soil Moisture (RSM)  
# def compute_rsm(img):
#   ''' function to compute Relative Soil Moisture'''

#   vv = img.select('VV')
#   # numerator = vv.subtract(min_ras.select('VV')) # old one
#   # rsm = numerator.divide(sensitivity.select('VV'))
#   numerator = vv.subtract(min_ras.select('VV_p5')) # new one
#   rsm = numerator.divide(sensitivity.select('VV_p95'))
#   return rsm

# Filter speckle noise
def filterSpeckles(img) :
  vv = img.select('VV')
  vv_smoothed = vv.focal_median(50,'circle','meters') #Apply a focal median filter
  return img.addBands(vv_smoothed, overwrite = True) # Add filtered VV band to original image

#  Function for calculating Relative Soil Moisture (RSM)  
def min_max(collection) :
  min_ras  = ee.Image(collection.reduce(ee.Reducer.percentile([5])))
  max_ras  = ee.Image(collection.reduce(ee.Reducer.percentile([95])))
  sensitivity = max_ras.subtract(min_ras)
  
  def compute_rsm(img) :
    vv = img.select('VV')
    numerator = vv.subtract(min_ras.select('VV_p5')) # new one
    rsm = numerator.divide(sensitivity.select('VV_p95'))
    return img.addBands(srcImg = rsm, overwrite = True)

  return collection.map(compute_rsm)

#  clip S1 image
def clipS1(img) :
  return img.clip(AOI)

# create sample rectangles
def mapRectangle(image) :
  return ee.Image(image).sampleRectangle(region = AOI, defaultValue = float(-9999))


# reducing resolution function
def reduce_resolution(image) :
  crs = (image.select('VV').projection()).crs()
  return image.reproject(crs = crs, scale = scale_res)

# reducing resolution function
def reduce_resolution_20(image) :
  crs = (image.select('VV').projection()).crs()
  return image.reproject(crs = crs, scale = 30)

# gamma0
def toGamma0(image) :
  return image.select('VV').subtract(image.select('angle').multiply(np.pi/180.0).cos().log10().multiply(10.0))

def powerToDb(img):
  return ee.Image(10).multiply(img.log10())


def dbToPower(img) :
  return ee.Image(10).pow(img.divide(10))


def refinedLee(imag) :
  bands = imag.bandNames()
  image = dbToPower(imag)
  
  def bandToImageCol(b) :
    img = image.select([b])
     
    # img must be in natural units, i.e. not in dB!
    # Set up 3x3 kernels 
    weights3 = ee.List.repeat(ee.List.repeat(1,3),3);
    kernel3 = ee.Kernel.fixed(3,3, weights3, 1, 1, False);
   
    mean3 = img.reduceNeighborhood(ee.Reducer.mean(), kernel3)
    variance3 = img.reduceNeighborhood(ee.Reducer.variance(), kernel3)
   
    # Use a sample of the 3x3 windows inside a 7x7 windows to determine gradients and directions
    sample_weights = ee.List([[0,0,0,0,0,0,0], [0,1,0,1,0,1,0],[0,0,0,0,0,0,0], [0,1,0,1,0,1,0], [0,0,0,0,0,0,0], [0,1,0,1,0,1,0],[0,0,0,0,0,0,0]])
   
    sample_kernel = ee.Kernel.fixed(7,7, sample_weights, 3,3, False)
   
    # Calculate mean and variance for the sampled windows and store as 9 bands
    sample_mean = mean3.neighborhoodToBands(sample_kernel)
    sample_var = variance3.neighborhoodToBands(sample_kernel)
   
    # Determine the 4 gradients for the sampled windows
    gradients = sample_mean.select(1).subtract(sample_mean.select(7)).abs()
    gradients = gradients.addBands(sample_mean.select(6).subtract(sample_mean.select(2)).abs())
    gradients = gradients.addBands(sample_mean.select(3).subtract(sample_mean.select(5)).abs())
    gradients = gradients.addBands(sample_mean.select(0).subtract(sample_mean.select(8)).abs())
   
    # And find the maximum gradient amongst gradient bands
    max_gradient = gradients.reduce(ee.Reducer.max())
   
    # Create a mask for band pixels that are the maximum gradient
    gradmask = gradients.eq(max_gradient);
   
    # duplicate gradmask bands: each gradient represents 2 directions
    gradmask = gradmask.addBands(gradmask);
   
    # Determine the 8 directions
    directions = sample_mean.select(1).subtract(sample_mean.select(4)).gt(sample_mean.select(4).subtract(sample_mean.select(7))).multiply(1)
    directions = directions.addBands(sample_mean.select(6).subtract(sample_mean.select(4)).gt(sample_mean.select(4).subtract(sample_mean.select(2))).multiply(2))
    directions = directions.addBands(sample_mean.select(3).subtract(sample_mean.select(4)).gt(sample_mean.select(4).subtract(sample_mean.select(5))).multiply(3))
    directions = directions.addBands(sample_mean.select(0).subtract(sample_mean.select(4)).gt(sample_mean.select(4).subtract(sample_mean.select(8))).multiply(4))
    # The next 4 are the not() of the previous 4
    directions = directions.addBands((directions.select(0).Not()).multiply(5))
    directions = directions.addBands((directions.select(1).Not()).multiply(6))
    directions = directions.addBands((directions.select(2).Not()).multiply(7))
    directions = directions.addBands((directions.select(3).Not()).multiply(8))
   
    # Mask all values that are not 1-8
    directions = directions.updateMask(gradmask)
   
    # "collapse" the stack into a singe band image (due to masking, each pixel has just one value (1-8) in it's directional band, and is otherwise masked)
    directions = directions.reduce(ee.Reducer.sum())  
   
    sample_stats = sample_var.divide(sample_mean.multiply(sample_mean));
   
    # Calculate localNoiseVariance
    sigmaV = sample_stats.toArray().arraySort().arraySlice(0,0,5).arrayReduce(ee.Reducer.mean(), [0])
   
    # Set up the 7*7 kernels for directional statistics
    rect_weights = ee.List.repeat(ee.List.repeat(0,7),3).cat(ee.List.repeat(ee.List.repeat(1,7),4))
   
    diag_weights = ee.List([[1,0,0,0,0,0,0], [1,1,0,0,0,0,0], [1,1,1,0,0,0,0], 
      [1,1,1,1,0,0,0], [1,1,1,1,1,0,0], [1,1,1,1,1,1,0], [1,1,1,1,1,1,1]])
   
    rect_kernel = ee.Kernel.fixed(7,7, rect_weights, 3, 3, False)
    diag_kernel = ee.Kernel.fixed(7,7, diag_weights, 3, 3, False)
   
    # Create stacks for mean and variance using the original kernels. Mask with relevant direction.
    dir_mean = img.reduceNeighborhood(ee.Reducer.mean(), rect_kernel).updateMask(directions.eq(1))
    dir_var = img.reduceNeighborhood(ee.Reducer.variance(), rect_kernel).updateMask(directions.eq(1))
   
    dir_mean = dir_mean.addBands(img.reduceNeighborhood(ee.Reducer.mean(), diag_kernel).updateMask(directions.eq(2)))
    dir_var = dir_var.addBands(img.reduceNeighborhood(ee.Reducer.variance(), diag_kernel).updateMask(directions.eq(2)))
   
    # and add the bands for rotated kernels
    for i in range(1,4) : # (var i=1; i<4; i++) {
      dir_mean = dir_mean.addBands(img.reduceNeighborhood(ee.Reducer.mean(), rect_kernel.rotate(i)).updateMask(directions.eq(2*i+1)))
      dir_var = dir_var.addBands(img.reduceNeighborhood(ee.Reducer.variance(), rect_kernel.rotate(i)).updateMask(directions.eq(2*i+1)))
      dir_mean = dir_mean.addBands(img.reduceNeighborhood(ee.Reducer.mean(), diag_kernel.rotate(i)).updateMask(directions.eq(2*i+2)))
      dir_var = dir_var.addBands(img.reduceNeighborhood(ee.Reducer.variance(), diag_kernel.rotate(i)).updateMask(directions.eq(2*i+2)))
   
    # "collapse" the stack into a single band image (due to masking, each pixel has just one value in it's directional band, and is otherwise masked)
    dir_mean = dir_mean.reduce(ee.Reducer.sum())
    dir_var = dir_var.reduce(ee.Reducer.sum())
   
    # A finally generate the filtered value
    varX = dir_var.subtract(dir_mean.multiply(dir_mean).multiply(sigmaV)).divide(sigmaV.add(1.0))
   
    b = varX.divide(dir_var)
   
    return dir_mean.add(b.multiply(img.subtract(dir_mean)))\
      .arrayProject([0])\
      .arrayFlatten([['sum']])\
      .float()
  
  result = ee.ImageCollection(bands.map(bandToImageCol)).toBands().rename(bands)
  return powerToDb(ee.Image(result)).copyProperties(imag, imag.propertyNames())

"""# **Colormap and stats variable generation**"""

# generating custom colormap
levels = [0, 0.2, 0.4, 0.6, 0.8, 1]
clrs = [(0, "#d7191c"), (0.25, "#fdae61"), (0.5, "#ffff00"), (0.75, "#00ff00"), (1, "#009cff")]
legend_elements = [Patch(facecolor='#009cff', edgecolor='black',label='Very High'), Patch(facecolor='#00ff00', edgecolor='black',label='High'), Patch(facecolor='#ffff00', edgecolor='black',label='Medium'), Patch(facecolor='#fdae61', edgecolor='black',label='Low'), Patch(facecolor='#d7191c', edgecolor='black',label='Very Low')]
cmap = colors.LinearSegmentedColormap.from_list('rsm', clrs, N=255)

"""# **Function for png generation and writing in S3**"""

def img_create(image, date, img, fig) :
  ''' function to create images and write them in s3'''

  img.set_data(image)

  # saving image in bytes to store in memory
  buf = io.BytesIO()
  fig.savefig(buf)
  buf.seek(0)

  plt.savefig(f"/home/satyukt/Projects/1259/Sitapur/Aalampur/sm/SM_{date}")

def main(coordinates) :
  try : 
    global AOI, min_ras, sensitivity, scale_res

    AOI = ee.Geometry.Polygon(coordinates)
    
    # generating farm polygon
    lon_list = [x[0] for x in coordinates]
    lat_list = [x[1] for x in coordinates]
    polygon_geom = Polygon(zip(lon_list, lat_list))
    crs = {'init': 'epsg:4326'}
    polygon = gpd.GeoDataFrame(index=[0], crs=crs, geometry=[polygon_geom])  

    extent_gdf = polygon.bounds.values[0]

    buff = 0.00008
    x_axis = [extent_gdf[0]-buff, extent_gdf[2]+buff]
    y_axis = [extent_gdf[1]-buff, extent_gdf[3]+buff]
    
    # generating MBR for farm polygon
    poly_bound = Polygon([[extent_gdf[0],extent_gdf[1]],
                          [extent_gdf[2],extent_gdf[1]],
                          [extent_gdf[2],extent_gdf[3]],
                          [extent_gdf[0],extent_gdf[3]]])
    polygon_bound = gpd.GeoDataFrame(index=[0], crs=crs, geometry=[poly_bound]) 
    
    # dataset collection
    dataset = (ee.ImageCollection('COPERNICUS/S1_GRD')
      # .filterDate((datetime.now() - timedelta(days = 365)).strftime('%Y-%m-%d'), (datetime.now()).strftime('%Y-%m-%d'))
      .filterDate('2021-07-01', '2022-07-01')
      .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
      .filter(ee.Filter.eq('instrumentMode', 'IW')).filterBounds(AOI))#.map(filterSpeckles))#.map(reduce_resolution_20))

    # image collection for relative soil moisture
    # rsm = dataset.filterDate((datetime.now() - timedelta(days = 365)).strftime('%Y-%m-%d'), (datetime.now()).strftime('%Y-%m-%d')) # segregate data for 6 months
    rsm = dataset.filterDate('2022-05-01', '2022-06-16') # segregate data for 6 months
    eedates = [x.split('_')[5][:8] for x in rsm.aggregate_array('system:id').getInfo()]
    s3dates = []
    limit = [eedates.index(x) for x in eedates if x not in s3dates]

    # calculate RSM for dates not present in S3
    if len(limit) > 0 :
      scale_res = 10
      # rsm = rsm.map(compute_rsm) # rsm calculated
      rsm = min_max(rsm)
      rsm_time_series = (rsm.map(mapRectangle)).toList(rsm.size()) # sample rectangle calculation
      arrayPlot = []
      for i in range(rsm.size().getInfo()) :
        arrayPlot.append(np.asarray(rsm_time_series.get(i).getInfo()['properties']['VV']))

      # creating plot handle for each farm
      fig, ax = plt.subplots(figsize=(5,5), facecolor = 'white')
      im = ax.imshow(arrayPlot[limit[0]], cmap = cmap, extent = [extent_gdf[0], extent_gdf[2], extent_gdf[1], extent_gdf[3]], vmin = 0, vmax = 1)
      (polygon.overlay(gpd.GeoDataFrame(geometry=polygon_bound.geometry.buffer(buff)), how='symmetric_difference')).plot(ax=ax, facecolor = 'white')
      polygon.plot(ax=ax, facecolor = 'none', edgecolor = 'black')
      ax.axis('off')
      cb1 = plt.colorbar(mappable = im, orientation="vertical", ticks = [round(x,1) for x in levels], fraction=0.03)
      ax.set_xlim(x_axis)
      ax.set_ylim(y_axis)
      fig.suptitle(f"Relative Soil Moisture", ha = 'center', fontsize=12, fontweight = 'bold')
      plt.legend(handles=legend_elements, loc='lower center', ncol = 5, bbox_to_anchor=(0.5,0), bbox_transform=plt.gcf().transFigure,  prop={'size': 8})
      plt.subplots_adjust(bottom=0.1, right=0.8, top=0.9)
#      plt.savefig(f"/home/satyukt/Projects/1001/sm_2.png")

      # calling plotting function  and passing the image handle
      for j in limit :
        in_array = arrayPlot[j].astype(float)
        in_array[in_array == -9999] = np.nan
        in_array[in_array < 0] = 0
        in_array[in_array > 1] = 1
        if ~np.isnan(in_array).all():
          # print('\n')
          img_create(in_array, eedates[j], im, fig)
        
  except ee.EEException as eex :
    print(f"earth engine error for -> {eex}")
    pass
  
  except Exception as e :
    print(f"error for -> {e}")
    pass

"""# **Calling main function**"""

shp_path = f"/home/satyukt/Projects/1001/shaas/Sitapur/Aalampur.shp"
gdf_ext_shp = (gpd.read_file(shp_path)).to_crs(4326)
geom = gdf_ext_shp["geometry"] 
jsonDict = eval(geom.to_json())
coordinates = jsonDict['features'][0]['geometry']['coordinates'][0]
main(coordinates)