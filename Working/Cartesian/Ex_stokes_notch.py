# %% [markdown]
# # The slab detachment benchmark
#
# Slab detachment benchark, as outlined  [Schmalholz, 2011](https://www.sciencedirect.com/science/article/pii/S0012821X11000252?casa_token=QzaaLiBMuiEAAAAA:wnpjH88ua6bj73EAjkoqmtiY5NWi9SmH7GSjvwvY_LNJi4CLk6vptoN93xM1kyAwdWa2rnbxa-U) and [Glerum et al., 2018](https://se.copernicus.org/articles/9/267/2018/se-9-267-2018.pdf)

# %%
from petsc4py import PETSc
import underworld3 as uw
from underworld3.systems import Stokes
import numpy as np
import sympy
from mpi4py import MPI

import os

from underworld3.utilities import generateXdmf

# %%
options = PETSc.Options()


options["snes_converged_reason"] = None
options["snes_monitor_short"] = None

sys = PETSc.Sys()
sys.pushErrorHandler("traceback")

# %%
### plot figs
if uw.mpi.size == 1:
    render = True
else:
    render = False
    
    
### linear or nonlinear version
linear = False ### False for NL version


# %%
## swarm gauss point count (particle distribution)
swarmGPC = 2

# %%
outputPath = './output/notchBenchmark/'


if uw.mpi.rank == 0:
    # checking if the directory demo_folder 
    # exist or not.
    if not os.path.exists(outputPath):

        # if the demo_folder directory is not present 
        # then create it.
        os.makedirs(outputPath)

# %% [markdown]
# #### Set up scaling of model

# %%
# import unit registry to make it easy to convert between units
u = uw.scaling.units

### make scaling easier
ndim = uw.scaling.non_dimensionalise
nd   = uw.scaling.non_dimensionalise
dim  = uw.scaling.dimensionalise 

# %%
### set reference values
refLength    = 100e3
refDensity   = 2.7e3
refGravity   = 9.81
refVelocity  = (1*u.centimeter/u.year).to(u.meter/u.second).m ### 1 cm/yr in m/s
refViscosity = 1e22
refPressure  = refDensity * refGravity * refLength
refTime      = refViscosity / refPressure

bodyforce    = refDensity  * u.kilogram / u.metre**3 * refGravity * u.meter / u.second**2

### create unit registry
KL = refLength * u.meter
Kt = refTime   * u.second
KM = bodyforce * KL**2 * Kt**2

scaling_coefficients                    = uw.scaling.get_coefficients()
scaling_coefficients["[length]"] = KL
scaling_coefficients["[time]"] = Kt
scaling_coefficients["[mass]"]= KM
scaling_coefficients

# %%

# %%
### fundamental values
ref_length    = uw.scaling.dimensionalise(1., u.meter).magnitude

ref_length_km = uw.scaling.dimensionalise(1., u.kilometer).magnitude

ref_density   =  uw.scaling.dimensionalise(1., u.kilogram/u.meter**3).magnitude

ref_gravity   = uw.scaling.dimensionalise(1., u.meter/u.second**2).magnitude

ref_temp      = uw.scaling.dimensionalise(1., u.kelvin).magnitude

ref_velocity  = uw.scaling.dimensionalise(1., u.meter/u.second).magnitude

### derived values
ref_time      = ref_length / ref_velocity

ref_time_Myr = dim(1, u.megayear).m

ref_pressure  = ref_density * ref_gravity * ref_length

ref_stress    = ref_pressure

ref_viscosity = ref_pressure * ref_time

### Key ND values
ND_gravity     = 9.81    / ref_gravity

# %%
### add material index
BGIndex    = 0
BrickIndex = 1

# %% [markdown]
# Set up dimensions of model and brick

# %%
xmin, xmax = 0., ndim(40*u.kilometer)
ymin, ymax = 0., ndim(10*u.kilometer)

## set brick height and length
BrickHeight = (400. / ref_length)
BrickLength = (800. / ref_length)

# %%
resx = 40
resy = 10

# %%
vel = ndim(2e-11 * u.meter / u.second)

# %% [markdown]
# ### Create mesh

# %%
# mesh = uw.meshing.UnstructuredSimplexBox(minCoords=(0.0,0.0), 
#                                               maxCoords=(1.0,1.0), 
#                                               cellSize=1.0/res, 
#                                               regular=True)

# mesh = uw.meshing.UnstructuredSimplexBox(minCoords=(xmin, ymin), maxCoords=(xmax, ymax), cellSize=1.0 / res, regular=False)


mesh = uw.meshing.StructuredQuadBox(elementRes =(int(resx),int(resy)),
                                    minCoords=(xmin,ymin), 
                                    maxCoords=(xmax,ymax))


# %% [markdown]
# ### Create Stokes object

# %%
v = uw.discretisation.MeshVariable('U',    mesh,  mesh.dim, degree=2 )
# p = uw.discretisation.MeshVariable('P',    mesh, 1, degree=1 )
p = uw.discretisation.MeshVariable('P',    mesh, 1, degree=1,  continuous=True)

strain_rate_inv2 = uw.discretisation.MeshVariable("SR", mesh, 1, degree=1)
dev_stress_inv2 = uw.discretisation.MeshVariable("stress", mesh, 1, degree=1)
node_viscosity = uw.discretisation.MeshVariable("viscosity", mesh, 1, degree=1)

timeField      = uw.discretisation.MeshVariable("time", mesh, 1, degree=1)
materialField  = uw.discretisation.MeshVariable("material", mesh, 1, degree=1)


# %%
stokes = uw.systems.Stokes(mesh, velocityField=v, pressureField=p )
stokes.constitutive_model = uw.systems.constitutive_models.ViscousFlowModel(mesh.dim)

# %% [markdown]
# #### Setup swarm

# %%
swarm     = uw.swarm.Swarm(mesh=mesh)

# material  = uw.swarm.IndexSwarmVariable("M", swarm, indices=2, proxy_continuous=False, proxy_degree=0)
material  = uw.swarm.IndexSwarmVariable("material", swarm, indices=2)

materialVariable      = swarm.add_variable(name="materialVariable", num_components=1, dtype=PETSc.IntType)

swarm.populate(fill_param=swarmGPC)

# %%
for i in [material, materialVariable]:
        with swarm.access(i):
            i.data[:] = BGIndex
            i.data[(swarm.data[:,1] <= BrickHeight) & 
                  (swarm.data[:,0] >= (((xmax - xmin) / 2.) - (BrickLength / 2.)) ) & 
                  (swarm.data[:,0] <= (((xmax - xmin) / 2.) + (BrickLength / 2.)) )] = BrickIndex



# %% [markdown]
# #### Additional files to save

# %%
nodal_strain_rate_inv2 = uw.systems.Projection(mesh, strain_rate_inv2)
nodal_strain_rate_inv2.uw_function = stokes._Einv2
nodal_strain_rate_inv2.smoothing = 0.
nodal_strain_rate_inv2.petsc_options.delValue("ksp_monitor")

nodal_visc_calc = uw.systems.Projection(mesh, node_viscosity)
nodal_visc_calc.uw_function = stokes.constitutive_model.Parameters.viscosity
nodal_visc_calc.smoothing = 0.
nodal_visc_calc.petsc_options.delValue("ksp_monitor")


nodal_tau_inv2 = uw.systems.Projection(mesh, dev_stress_inv2)
nodal_tau_inv2.uw_function = 2. * stokes.constitutive_model.Parameters.viscosity * stokes._Einv2
nodal_tau_inv2.smoothing = 0.
nodal_tau_inv2.petsc_options.delValue("ksp_monitor")

matProj = uw.systems.Projection(mesh, materialField)
matProj.uw_function = materialVariable.sym[0]
matProj.smoothing = 0.
matProj.petsc_options.delValue("ksp_monitor")


# %%
def updateFields(time):
    
    with mesh.access(timeField):
        timeField.data[:,0] = dim(time, u.megayear).m

    nodal_strain_rate_inv2.solve()

    
    matProj.uw_function = materialVariable.sym[0] 
    matProj.solve(_force_setup=True)


    nodal_visc_calc.uw_function = stokes.constitutive_model.Parameters.viscosity
    nodal_visc_calc.solve(_force_setup=True)

    nodal_tau_inv2.uw_function = 2. * stokes.constitutive_model.Parameters.viscosity * stokes._Einv2
    nodal_tau_inv2.solve(_force_setup=True)

# %% [markdown]
# #### Boundary conditions

# %%
stokes.add_dirichlet_bc(sympy.Matrix([   vel,0.]), "Left", [0,1])
stokes.add_dirichlet_bc(sympy.Matrix([-1*vel,0.]), "Right", [0,1])


stokes.add_dirichlet_bc(0.0, "Bottom", 1)


# %%
def globalPassiveSwarmCoords(swarm, bcast=True, rootProc=0):
    '''
    Distribute passive swarm coordinate data to all CPUs (bcast = True) or the rootProc, (bcast = False)
    
    Used for the analysis of coordinates of swarm that may move between processors
    
    '''
    
    comm = uw.mpi.comm
    rank = uw.mpi.rank
    size = uw.mpi.size
    

    with swarm.access():
        if len(swarm.data) > 0:
            x_local = np.ascontiguousarray(swarm.data[:,0].copy())
            y_local = np.ascontiguousarray(swarm.data[:,1].copy())
            if swarm.data.shape[1] == 3:
                z_local = np.ascontiguousarray(swarm.data[:,2].copy())
            else:
                z_local = np.zeros_like(swarm.data[:,0])*np.nan
                
        else:
            x_local = np.array([np.nan], dtype='float64')
            y_local = np.array([np.nan], dtype='float64')
            z_local = np.array([np.nan], dtype='float64')
            
            
            
    ### Collect local array sizes using the high-level mpi4py gather
    sendcounts = np.array(comm.gather(len(x_local), root=rootProc))
    
    
    if rank == rootProc:
        x_global = np.zeros((sum(sendcounts)), dtype='float64')
        y_global = np.zeros((sum(sendcounts)), dtype='float64')
        z_global = np.zeros((sum(sendcounts)), dtype='float64')
    else:
        x_global = None
        y_global = None
        z_global = None
        

    comm.barrier()

    ## gather x values, can't do them together
    comm.Gatherv(sendbuf=x_local, recvbuf=(x_global, sendcounts), root=rootProc)
    ## gather y values
    comm.Gatherv(sendbuf=y_local, recvbuf=(y_global, sendcounts), root=rootProc)

    ## gather z values
    comm.Gatherv(sendbuf=z_local, recvbuf=(z_global, sendcounts), root=rootProc)
    
    comm.barrier()
    
    def sortCoords():
        ## Put back into combined array
        Coords = np.zeros(shape=(len(x_global),3))*np.nan
        Coords[:,0] = x_global
        Coords[:,1] = y_global
        Coords[:,2] = z_global
        
        comm.barrier()

        ### remove rows with NaN
        Coords = Coords[~np.isnan(Coords[:,0])]
        ### remove cols with NaN
        Coords = Coords[:, ~np.isnan(Coords).all(axis=0)]
        
        comm.barrier()
        
        return Coords
    
    if bcast == True:
        #### make swarm coords available on all processors
        x_global = comm.bcast(x_global, root=rootProc)
        y_global = comm.bcast(y_global, root=rootProc)
        z_global = comm.bcast(z_global, root=rootProc)
        
        comm.barrier()
        
        Coords = sortCoords()
        
        comm.barrier()
           
    else:
        ### swarm coords only available on root processor
        if rank == rootProc:
            Coords = sortCoords()
            
        comm.barrier()
            
    return Coords


# %% [markdown]
# #### Set up density of materials

# %%
### set density of materials
densityBG      = 2700/ref_density
densityBrick   = 2700/ref_density

# %%
mat_density = np.array([densityBG, densityBrick])

density = mat_density[0] * material.sym[0] + \
          mat_density[1] * material.sym[1]

stokes.bodyforce = sympy.Matrix([0, -1 * ND_gravity * density])


# %% [markdown]
# ### Create figure function

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


    mesh.vtk("tempMsh.vtk")
    pvmesh = pv.read("tempMsh.vtk") 

    with swarm.access():
        points = np.zeros((swarm.data.shape[0],3))
        points[:,0] = swarm.data[:,0]
        points[:,1] = swarm.data[:,1]
        points[:,2] = 0.0

    point_cloud = pv.PolyData(points)
    
    # ### create point cloud for passive tracers
    # with passiveSwarm.access():
    #     passiveCloud = pv.PolyData(np.vstack((passiveSwarm.data[:,0],passiveSwarm.data[:,1], np.zeros(len(passiveSwarm.data)))).T)


    with swarm.access():
        point_cloud.point_data["M"] = material.data.copy()
        



    pl = pv.Plotter(notebook=True)

    pl.add_mesh(pvmesh,'Black', 'wireframe')

    # pl.add_points(point_cloud, color="Black",
    #                   render_points_as_spheres=False,
    #                   point_size=2.5, opacity=0.75)       



    pl.add_mesh(point_cloud, cmap="coolwarm", edge_color="Black", show_edges=False, scalars="M",
                        use_transparency=False, opacity=0.95)
    
    # ### add points of passive tracers
    # pl.add_mesh(passiveCloud, color='black', show_edges=True,
    #                 use_transparency=False, opacity=0.95)



    pl.show(cpos="xy")
    
if render == True & uw.mpi.size==1:
    plot_mat()


# %% [markdown]
# #### Create function to save mesh and swarm vars

# %%
def saveData(step, outputPath, time):
    
    ### save mesh vars
    fname = f"{outputPath}mesh_{'step_'}{step:02d}.h5"
    xfname = f"{outputPath}mesh_{'step_'}{step:02d}.xmf"
    viewer = PETSc.ViewerHDF5().createHDF5(fname, mode=PETSc.Viewer.Mode.WRITE,  comm=PETSc.COMM_WORLD)

    viewer(mesh.dm)

    ### add mesh vars to viewer to save as one h5/xdmf file. Has to be a PETSc object (?)
    viewer(stokes.u._gvec)         # add velocity
    viewer(stokes.p._gvec)         # add pressure
    viewer(strain_rate_inv2._gvec) # add strain rate
    viewer(node_viscosity._gvec)   # add viscosity
    viewer(materialField._gvec)    # add material projection
    viewer(timeField._gvec)        # add time
    viewer.destroy()              
    generateXdmf(fname, xfname)
    
    ### save all swarm variables attached to DM
    x_swarm_fname = f"{outputPath}swarm_{'step_'}{step:02d}.xmf"
    swarm.dm.viewXDMF(x_swarm_fname)


# %%
# Set solve options here (or remove default values
stokes.petsc_options["ksp_monitor"] = None

stokes.tolerance = 1.0e-4
### snes_atol has to be =< 1e-3 (dependent on res) otherwise it will not solve
stokes.petsc_options["snes_atol"] = 1e-4

stokes.petsc_options["ksp_atol"] = 1e-2

# stokes.petsc_options["fieldsplit_velocity_ksp_rtol"] = 1e-4
# stokes.petsc_options["fieldsplit_pressure_ksp_type"] = "gmres" # gmres here for bulletproof
stokes.petsc_options[
    "fieldsplit_pressure_pc_type"
] = "gamg"  # can use gasm / gamg / lu here
stokes.petsc_options[
    "fieldsplit_pressure_pc_gasm_type"
] = "basic"  # can use gasm / gamg / lu here
stokes.petsc_options[
    "fieldsplit_pressure_pc_gamg_type"
] = "classical"  # can use gasm / gamg / lu here
stokes.petsc_options["fieldsplit_pressure_pc_gamg_classical_type"] = "direct"
# # stokes.petsc_options["fieldsplit_velocity_pc_gamg_agg_nsmooths"] = 5
# # stokes.petsc_options["fieldsplit_velocity_mg_levels_ksp_max_it"] = 5
# # stokes.petsc_options["fieldsplit_pressure_mg_levels_ksp_converged_maxits"] = None


# # Fast: preonly plus gasm / gamg / mumps
# # Robust: gmres plus gasm / gamg / mumps

# stokes.petsc_options["fieldsplit_velocity_pc_type"] = "gamg"
# # stokes.petsc_options["fieldsplit_velocity_pc_gasm_type"] = "basic" # can use gasm / gamg / lu here

# stokes.petsc_options["fieldsplit_velocity_pc_gamg_agg_nsmooths"] = 2
# stokes.petsc_options["fieldsplit_velocity_mg_levels_ksp_max_it"] = 3

# stokes.petsc_options["fieldsplit_velocity_pc_gamg_esteig_ksp_type"] = "cg"
stokes.petsc_options["fieldsplit_pressure_pc_gamg_esteig_ksp_type"] = "cg"


# %% [markdown]
# ### Initial linear solve
# viscosity is limited between 10$^{20}$ and 10$^{24}$ Pa S

# %%
minVisc = nd(1e20 *u.pascal*u.second)
maxVisc = nd(1e24 *u.pascal*u.second)

# %%
### linear solve
stokes.constitutive_model.Parameters.viscosity = minVisc
stokes.saddle_preconditioner = 1.0 / ndim(ref_viscosity * u.pascal*u.second)


# %%
stokes.solve(zero_init_guess=True)

# %% [markdown]
# #### Linear solve with different viscosities

# %%
### linear viscosity

viscosityL = np.array([maxVisc, minVisc])

viscosityL   = viscosityL[0] * material.sym[0] + \
               viscosityL[1] * material.sym[1]  


stokes.constitutive_model.Parameters.viscosity = viscosityL

stokes.saddle_preconditioner = 1 / viscosityL

# stokes.saddle_preconditioner = 1.0 / stokes.constitutive_model.Parameters.viscosity
stokes.solve(zero_init_guess=False)



# %% [markdown]
# #### Solve for NL BG material

# %%
### Set the viscosity of the brick
viscBrick        = nd(1e20 *u.pascal*u.second)

if linear == False: 
    n = 4
    BG_visc       = nd(4.75e11*u.pascal*u.second**(1/n))
    BG_visc       = BG_visc * sympy.Pow(stokes._Einv2, (1/n-1))


else:
    BG_visc      = nd(2e23*u.pascal*u.second) #4.75*1e11/ref_viscosity
    BG_visc       = BG_visc * (stokes._Einv2)

# C = nd(40e6*u.pascal)

# if linear == False:
#     BG_visc = C / (2*stokes._Einv2)
    
# else:
#     BG_visc = C / (2*nd(1e-15/u.second))



mat_viscosity = np.array([BG_visc, viscBrick])

viscosityMat = mat_viscosity[0] * material.sym[0] + \
               mat_viscosity[1] * material.sym[1] 

### add in material-based viscosity

viscosity = sympy.Max(sympy.Min(viscosityMat, maxVisc ), minVisc )

stokes.constitutive_model.Parameters.viscosity = viscosity
stokes.saddle_preconditioner = 1.0 / viscosity

stokes.penalty = 0.1

stokes.solve(zero_init_guess=False)
dt = stokes.estimate_dt()

# %%
### Set the viscosity of the brick
viscBrick        = nd(1e20 *u.pascal*u.second)

C = nd(40e6 *u.pascal)

if linear == False: 
    BG_visc = C / (2*stokes._Einv2)
    
else:
    BG_visc = C / (2*nd(1e-15/u.second))




mat_viscosity = np.array([BG_visc, viscBrick])

viscosityMat = mat_viscosity[0] * material.sym[0] + \
               mat_viscosity[1] * material.sym[1] 

### add in material-based viscosity

viscosity = sympy.Max(sympy.Min(viscosityMat, maxVisc ), minVisc )

stokes.constitutive_model.Parameters.viscosity = viscosity
stokes.saddle_preconditioner = 1.0 / viscosity

stokes.penalty = 0.1

stokes.solve(zero_init_guess=False)
dt = stokes.estimate_dt()

# %% [markdown]
# #### Check the results against the benchmark 

# %%
if uw.mpi.size==1 and render == True:
    import numpy as np
    import pyvista as pv
    import vtk

    pv.global_theme.background = "white"
    pv.global_theme.window_size = [1050, 500]
    pv.global_theme.antialiasing = True
    pv.global_theme.jupyter_backend = "panel"
    pv.global_theme.smooth_shading = True
    pv.global_theme.camera["viewup"] = [0.0, 1.0, 0.0]
    pv.global_theme.camera["position"] = [0.0, 0.0, 1.0]

    mesh.vtk("tmp_mesh.vtk")
    pvmesh = pv.read("tmp_mesh.vtk")

    points = np.zeros((mesh._centroids.shape[0], 3))
    points[:, 0] = mesh._centroids[:, 0]
    points[:, 1] = mesh._centroids[:, 1]


    pvmesh.point_data["pres"] = uw.function.evaluate(
        p.sym[0], mesh.data
    )
    


    # pvmesh.point_data["edot"] = uw.function.evaluate(strain_rate_inv2.sym[0], mesh.data)
    # # pvmesh.point_data["tauy"] = uw.function.evaluate(tau_y, mesh.data, mesh.N)
    # pvmesh.point_data["eta"] = uw.function.evaluate(node_viscosity.sym[0], mesh.data)
    # pvmesh.point_data["str"] = uw.function.evaluate(dev_stress_inv2.sym[0], mesh.data)
    
    with mesh.access():
        pvmesh.point_data["edot"] = strain_rate_inv2.data
        pvmesh.point_data["eta"]  = node_viscosity.data
        pvmesh.point_data["str"]  = dev_stress_inv2.data

    with mesh.access():
        usol = v.data.copy()

    arrow_loc = np.zeros((v.coords.shape[0], 3))
    arrow_loc[:, 0:2] = v.coords[...]

    arrow_length = np.zeros((v.coords.shape[0], 3))
    arrow_length[:, 0:2] = usol[...]

    point_cloud0 = pv.PolyData(points)

    with swarm.access():
        point_cloud = pv.PolyData( np.zeros((swarm.data.shape[0], 3))  )
        point_cloud.points[:,0:2] = swarm.data[:]
        point_cloud.point_data["M"] = material.data.copy()
        point_cloud.point_data["edot"] = uw.function.evaluate(strain_rate_inv2.sym[0], swarm.data)



# %%
if uw.mpi.size==1 and render == True:
    pl = pv.Plotter()

    # pl.add_arrows(arrow_loc, arrow_length, mag=0.03, opacity=0.75)

    pl.add_mesh(
        pvmesh,
        cmap="coolwarm",
        scalars="edot",
        edge_color="Grey",
        show_edges=True,
        use_transparency=False,
        log_scale=True,
        # clim=[0.1,2.1],
        opacity=1.0,
    )
    
    # pl.add_mesh(point_cloud, cmap="coolwarm", edge_color="Black", show_edges=False, scalars="edot",
    #                     use_transparency=False, opacity=0.1, log_scale=True)

    pl.add_points(
        point_cloud,
        cmap="coolwarm",
        scalars="edot",
        render_points_as_spheres=False,
        point_size=10,
        opacity=0.3,
        log_scale=True
    )

    pl.show(cpos="xy")

# %%
point_cloud.point_data["edot"]

# %%
