#!/usr/bin/env python
# coding: utf-8
# %% [markdown]
# # Slab subduction
#
#
# #### [From Dan Sandiford](https://github.com/dansand/uw3_models/blob/main/slabsubduction.ipynb)
#
#
#
# UW2 example ported to UW3 

# %%
import numpy as np
import os
import math
from petsc4py import PETSc
import underworld3 as uw

import sympy


from underworld3.utilities import generateXdmf


from sympy import Piecewise, ceiling, Abs, Min, sqrt, eye, Matrix, Max


# %%
outputPath = 'output/slabSubduction/'

if uw.mpi.rank==0:      
    ### create folder if not run before
    if not os.path.exists(outputPath):
        os.makedirs(outputPath)


# %%
### For visualisation
render = True


# %%
options = PETSc.Options()

options["snes_converged_reason"] = None
options["snes_monitor_short"] = None



# %%
n_els     =  48
dim       =   2
boxLength = 4.0
boxHeight = 1.0
ppcell    =   5

# %% [markdown]
# ### Create mesh and mesh vars

# %%
mesh = uw.meshing.StructuredQuadBox(elementRes=(    4*n_els,n_els), 
                    minCoords =(       0.,)*dim, 
                    maxCoords =(boxLength,boxHeight), qdegree=3 )





# %%
v = uw.discretisation.MeshVariable("V", mesh, mesh.dim, degree=mesh.qdegree)
p = uw.discretisation.MeshVariable("P", mesh, 1, degree=1)

strain_rate_inv2 = uw.discretisation.MeshVariable("SR", mesh, 1, degree=mesh.qdegree)
node_viscosity   = uw.discretisation.MeshVariable("Viscosity", mesh, 1, degree=1)
# materialField    = uw.discretisation.MeshVariable("Material", mesh, 1, degree=1)



# %%
stokes = uw.systems.Stokes(mesh, velocityField=v, pressureField=p)
stokes.constitutive_model = uw.systems.constitutive_models.ViscousFlowModel(mesh.dim)

# %% [markdown]
# ### Create swarm and swarm vars
# - 'swarm.add_variable' is a traditional swarm, can't be used to map material properties. Can be used for sympy operations, similar to mesh vars.
# - 'uw.swarm.IndexSwarmVariable', creates a mask for each material and can be used to map material properties. Can't be used for sympy operations.
#

# %%
swarm  = uw.swarm.Swarm(mesh)

# %%
## # Add index swarm variable for material
material              = uw.swarm.IndexSwarmVariable("M", swarm, indices=5) 

strain = swarm.add_variable('strain')

swarm.populate(3)

# Add some randomness to the particle distribution
import numpy as np
np.random.seed(0)

with swarm.access(swarm.particle_coordinates):
    factor = 0.5*boxLength/n_els/ppcell
    swarm.particle_coordinates.data[:] += factor*np.random.rand(*swarm.particle_coordinates.data.shape)
      


# %% [markdown]
# #### Project fields to mesh vars
# Useful for visualising stuff on the mesh (Viscosity, material, strain rate etc) and saving to a grouped xdmf file


# %%
# material.info()
# """
# you have 5 materials
# if you want to have material variable rheologies, density
# """
# phi 1 = material.piecewise([m1_visc,2,3,4,5])
# phi_2 = material.piecewise([m1_rho, m2_rho, m3_rho])

# %%
nodal_strain_rate_inv2 = uw.systems.Projection(mesh, strain_rate_inv2)
nodal_strain_rate_inv2.uw_function = stokes._Einv2
nodal_strain_rate_inv2.smoothing = 0.0
nodal_strain_rate_inv2.petsc_options.delValue("ksp_monitor")

nodal_visc_calc = uw.systems.Projection(mesh, node_viscosity)
nodal_visc_calc.uw_function = stokes.constitutive_model.Parameters.viscosity
# nodal_visc_calc.smoothing = 1.0e-3
nodal_visc_calc.petsc_options.delValue("ksp_monitor")

# meshMat = uw.systems.Projection(mesh, materialField)
# meshMat.uw_function = material.sym
# # meshMat.smoothing = 1.0e-3
# meshMat.petsc_options.delValue("ksp_monitor")

def updateSR():
    ### update strain rate
    nodal_strain_rate_inv2.uw_function = stokes._Einv2
    nodal_strain_rate_inv2.solve()
    
    with mesh.access(strain_rate_inv2):
        #### sometimes get negative values (???)
        strain_rate_inv2.data[strain_rate_inv2.data < 0.] = 0.
    
def updateVisc():
    ### update viscosity
    nodal_visc_calc.uw_function = stokes.constitutive_model.Parameters.viscosity
    nodal_visc_calc.solve(_force_setup=True)

def updateFields():
    updateSR()
    updateVisc()



    
    # ### update material field from swarm
    # meshMat.uw_function = material.sym
    # meshMat.solve(_force_setup=True)
    
def update_strain(dt, strain_var, healingRate=0.):
    updateSR()
    with swarm.access(strain):
        ### rbf interpolate is quicker, does not produce negative results.
        ### how does this work in parallel?
        SR_swarm = strain_rate_inv2.rbf_interpolate(strain_var.swarm.data)[:,0] 
        
        ### function evaluate (projection) produces negative SR results
        # SR_swarm = uw.function.evaluate(strain_rate_inv2.sym[0], strain_var.swarm.data)
        
        #### dt / SR 
        ### add the strain into the model
        strain_var.data[:,0] += (dt * SR_swarm)
        ### heal the strain at a given rate
        strain_var.data[:,0] -= (dt * healingRate)
        ### make sure the healing does not go below zero
        strain_var.data[strain_var.data < 0] = 0.



# %% [markdown]
# ## Setup the material distribution


# %%
import matplotlib.path as mpltPath

### initialise the 'material' data to represent two different materials. 
upperMantleIndex = 0
lowerMantleIndex = 1
upperSlabIndex   = 2
lowerSlabIndex   = 3
coreSlabIndex    = 4

### Initial material layout has a flat lying slab with at 15\degree perturbation
lowerMantleY   = 0.4
slabLowerShape = np.array([ (1.2,0.925 ), (3.25,0.925 ), (3.20,0.900), (1.2,0.900), (1.02,0.825), (1.02,0.850) ])
slabCoreShape  = np.array([ (1.2,0.975 ), (3.35,0.975 ), (3.25,0.925), (1.2,0.925), (1.02,0.850), (1.02,0.900) ])
slabUpperShape = np.array([ (1.2,1.000 ), (3.40,1.000 ), (3.35,0.975), (1.2,0.975), (1.02,0.900), (1.02,0.925) ])


# %%
slabLower  = mpltPath.Path(slabLowerShape)
slabCore   = mpltPath.Path(slabCoreShape)
slabUpper  = mpltPath.Path(slabUpperShape)


# %% [markdown]
# ### Update the material variable of the swarm

# %%
with swarm.access(swarm.particle_coordinates, material):

    ### for the symbolic mapping of material properties
    material.data[:] = upperMantleIndex
    material.data[swarm.particle_coordinates.data[:,1] < lowerMantleY]           = lowerMantleIndex
    material.data[slabLower.contains_points(swarm.particle_coordinates.data[:])] = lowerSlabIndex
    material.data[slabCore.contains_points(swarm.particle_coordinates.data[:])]  = coreSlabIndex
    material.data[slabUpper.contains_points(swarm.particle_coordinates.data[:])] = upperSlabIndex
    
    
    


# %%
def plot_mat():

    import numpy as np
    import pyvista as pv
    import vtk

    pv.global_theme.background = 'white'
    pv.global_theme.window_size = [750, 750]
    pv.global_theme.antialiasing = True
    pv.global_theme.jupyter_backend = 'panel'
    pv.global_theme.smooth_shading = True


    mesh.vtk(outputPath + "tempMsh.vtk")
    pvmesh = pv.read(outputPath + "tempMsh.vtk") 

    with swarm.access():
        points = np.zeros((swarm.data.shape[0],3))
        points[:,0] = swarm.data[:,0]
        points[:,1] = swarm.data[:,1]
        points[:,2] = 0.0

    point_cloud = pv.PolyData(points)


    with swarm.access():
        point_cloud.point_data["M"] = material.data.copy()



    pl = pv.Plotter(notebook=True)

    pl.add_mesh(pvmesh,'Black', 'wireframe')

    # pl.add_points(point_cloud, color="Black",
    #                   render_points_as_spheres=False,
    #                   point_size=2.5, opacity=0.75)       



    pl.add_mesh(point_cloud, cmap="coolwarm", edge_color="Black", show_edges=False, scalars="M",
                        use_transparency=False, opacity=0.95)



    pl.show(cpos="xy")
 
if render == True:
    plot_mat()


# %% [markdown]
# ### Function to save output of model
# Saves both the mesh vars and swarm vars

# %%
def saveData(step, outputPath):

    mesh.petsc_save_checkpoint(meshVars=[v, p, strain_rate_inv2, node_viscosity], index=step, outputPath=outputPath)
    
    swarm.petsc_save_checkpoint(swarmName='swarm', index=step, outputPath=outputPath)
    


# %% [markdown]
# #### Density

# %%
mantleDensity = 0.5
slabDensity   = 1.0 

density_fn = material.createMask([mantleDensity, 
                                 mantleDensity,
                                 slabDensity,
                                 slabDensity,
                                 slabDensity])





stokes.bodyforce =  Matrix([0, -1 * density_fn])


# %% [markdown]
# ### Boundary conditions
#
# Free slip by only constraining one component of velocity 

# %%
#free slip
stokes.add_dirichlet_bc( (0.,0.), 'Left',   (0) ) # left/right: function, boundaries, components
stokes.add_dirichlet_bc( (0.,0.), 'Right',  (0) )

stokes.add_dirichlet_bc( (0.,0.), 'Top',    (1) )
stokes.add_dirichlet_bc( (0.,0.), 'Bottom', (1) )# top/bottom: function, boundaries, components 

# %% [markdown]
# ###### initial first guess of constant viscosity

# %%
if uw.mpi.size == 1:
    stokes.petsc_options['pc_type'] = 'lu'

stokes.petsc_options["snes_max_it"] = 500

stokes.tolerance = 1e-6

# %%
### initial linear solve
stokes.constitutive_model.Parameters.viscosity  = 1.

stokes.saddle_preconditioner = 1 / stokes.constitutive_model.Parameters.viscosity

stokes.solve(zero_init_guess=True)


# %% [markdown]
# #### add in NL rheology for solve loop

# %%
### viscosity from UW2 example
upperMantleViscosity =    1.0
lowerMantleViscosity =  100.0
slabViscosity        =  500.0
coreViscosity        =  500.0


strainRate_2ndInvariant = stokes._Einv2


cohesion = 0.06
cohesionW = 0.01


# %%
def material_weakening_piecewise(strain_var, val1, val2, epsilon1, epsilon2):
    val = sympy.Piecewise((val1, strain_var.sym[0] < epsilon1),
                            (val2, strain_var.sym[0] > epsilon2),
                            (val1 + ((val1 - val2) / (epsilon1 - epsilon2)) * (strain_var.sym[0] - epsilon1), True) )
    
    return val 
    


# %%
cohesion_fn = mat_strength_change(strain, cohesion, cohesionW, 0.5, 1.5) # material_weakening(strain, cohesion, cohesionW, 0.5, 1.5)
vonMises = 0.5 * cohesion_fn / (strainRate_2ndInvariant+1.0e-18)


# The upper slab viscosity is the minimum of the 'slabViscosity' or the 'vonMises' 
slabYieldvisc =  Min(vonMises, slabViscosity)

# %%
viscosity_fn = material.createMask([upperMantleViscosity,
                                    lowerMantleViscosity,
                                    slabYieldvisc,
                                    slabYieldvisc,
                                    coreViscosity])

# %%
stokes.constitutive_model.Parameters.viscosity = viscosity_fn

# %%
stokes.saddle_preconditioner = 1 / stokes.constitutive_model.Parameters.viscosity

# %% [markdown]
# ### Main loop
# Stokes solve loop

# %%
step      = 0
max_steps = 50
time      = 0



while step<max_steps:
    
    print(f'\nstep: {step}, time: {time}')
          
    #viz for parallel case - write the hdf5s/xdmfs 
    if step%2==0:
        if uw.mpi.rank == 0:
            print(f'\nSave data: ')
            
        ### updates projection of fields to the mesh
        updateFields()
        
        ### saves the mesh and swarm
        saveData(step, outputPath)
        

            
    
    if uw.mpi.rank == 0:
        print(f'\nStokes solve: ')  
        
    stokes.solve(zero_init_guess=False)
    
    ### get the timestep
    dt = stokes.estimate_dt()
    
    update_strain(dt=dt, strain_var=strain)
 
    ### advect the particles according to the timestep
    swarm.advection(V_fn=stokes.u.sym, delta_t=dt, corrector=False)
        
    step += 1
    
    time += dt




# %%
with swarm.access(strain):
    print(strain.data.min())
    print(strain.data.max())

# %%
with swarm.access(strain):
    coh = uw.function.evaluate(  cohesion_fn, strain.swarm.data[:,])
    print(f'strain min: {strain.data.min()}, max: {strain.data.max()}')
    print(f'cohesion min: {coh.min()}, max: {coh.max()}')


# %%
def plot_mat():

    import numpy as np
    import pyvista as pv
    import vtk

    pv.global_theme.background = 'white'
    pv.global_theme.window_size = [750, 750]
    pv.global_theme.antialiasing = True
    pv.global_theme.jupyter_backend = 'panel'
    pv.global_theme.smooth_shading = True


    mesh.vtk(outputPath + "tempMsh.vtk")
    pvmesh = pv.read(outputPath + "tempMsh.vtk") 

    with swarm.access():
        points = np.zeros((swarm.data.shape[0],3))
        points[:,0] = swarm.data[:,0]
        points[:,1] = swarm.data[:,1]
        points[:,2] = 0.0

    point_cloud = pv.PolyData(points)


    with swarm.access(strain):
        point_cloud.point_data["strain"] = strain.data.copy()
        point_cloud.point_data["M"] = material.data.copy()



    pl = pv.Plotter(notebook=True)

    pl.add_mesh(pvmesh,'Black', 'wireframe')

    # pl.add_points(point_cloud, color="Black",
    #                   render_points_as_spheres=False,
    #                   point_size=2.5, opacity=0.75)       




    
    pl.add_mesh(point_cloud, cmap="coolwarm", edge_color="Black", show_edges=False, scalars="M",
                        use_transparency=False, opacity=0.7)
    
    pl.add_mesh(point_cloud, cmap="coolwarm", edge_color="Black", show_edges=False, scalars="strain",
                        use_transparency=False, opacity=0.1)



    pl.show(cpos="xy")
 
if render == True:
    plot_mat()

# %%
