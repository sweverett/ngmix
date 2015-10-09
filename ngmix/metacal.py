"""
class to create manipulated images for use in metacalibration

based off reading through Eric Huffs code, but it has departed
significantly

"""
from __future__ import print_function
import numpy
from numpy import zeros, ones, newaxis, sqrt, diag, dot, linalg, array
from .jacobian import Jacobian, UnitJacobian
from .observation import Observation
from .shape import Shape

LANCZOS_PARS_DEFAULT={'order':5, 'conserve_dc':True, 'tol':1.0e-4}

class Metacal(object):
    """
    Create manipulated images for use in metacalibration

    parameters
    ----------
    image: numpy array
        2d array representing the image
    psf_image: numpy array
        2d array representing the psf image
    jacobian: Jacobian, optional
        An ngmix.Jacobian or None.  If None, an ngmix.UnitJacobian is
        constructed
    lanczos_pars: dict, optional
        The lanczos pars.  Default is 
        {'order':5, 'conserve_dc':True, 'tol':1.0e-4}

    examples
    --------

    psf_obs=Observation(psf_image)
    obs=Observation(image, psf=psf_obs)

    mc=Metacal(obs)

    # observations used to calculate R

    sh1m=ngmix.Shape(-0.01,  0.00 )
    sh1p=ngmix.Shape( 0.01,  0.00 )
    sh2m=ngmix.Shape( 0.00, -0.01 )
    sh2p=ngmix.Shape( 0.00,  0.01 )

    R_obs1m = mc.get_obs_galshear(sh1m)
    R_obs1p = mc.get_obs_galshear(sh1p)
    R_obs2m = mc.get_obs_galshear(sh2m)
    R_obs2p = mc.get_obs_galshear(sh2p)

    # you can also get an unsheared, just convolved obs
    R_obs1m, R_obs1m_unsheared = mc.get_obs_galshear(sh1p, get_unsheared=True)

    # observations used to calculate Rpsf
    Rpsf_obs1m = mc.get_obs_psfshear(sh1m)
    Rpsf_obs1p = mc.get_obs_psfshear(sh1p)
    Rpsf_obs2m = mc.get_obs_psfshear(sh2m)
    Rpsf_obs2p = mc.get_obs_psfshear(sh2p)
    """

    # for caching symmetrized noise realizations, which we only do based on the
    # shear or psf shear
    sym_cache={}

    def __init__(self,
                 obs,
                 lanczos_pars=None,
                 whiten=False,
                 symmetrize=False,
                 same_seed=False):

        self._set_data(obs,
                       lanczos_pars=lanczos_pars,
                       whiten=whiten,
                       symmetrize=symmetrize,
                       same_seed=same_seed)

    def get_obs_galshear(self, shear, get_unsheared=False):
        """
        This is the case where we shear the image, for calculating R

        parameters
        ----------
        shear: ngmix.Shape
            The shear to apply

        get_unsheared: bool
            Get an observation only convolved by the target psf, not
            sheared
        """

        newpsf, newpsf_interp = self.get_target_psf(shear, 'gal_shear')
        sheared_image = self.get_target_image(newpsf_interp, shear=shear)
        if self.symmetrize:
            sheared_image = self._symmetrize_noise('gal',
                                                   sheared_image,
                                                   newpsf_interp,
                                                   shear)

        newobs = self._make_obs(sheared_image, newpsf)

        if get_unsheared:
            unsheared_image = self.get_target_image(newpsf_interp, shear=None)
            unsheared_image = self._symmetrize_noise('gal',
                                                     unsheared_image,
                                                     newpsf_interp,
                                                     Shape(0.0,0.0))


            uobs = self._make_obs(unsheared_image, newpsf)
            return newobs, uobs
        else:
            return newobs

    def get_obs_dilated_only(self, shear):
        """
        Unsheared image, just with psf dilated

        parameters
        ----------
        shear: ngmix.Shape
            The shear to apply
        """

        newpsf, newpsf_interp = self.get_target_psf(shear, 'gal_shear')
        unsheared_image = self.get_target_image(newpsf_interp, shear=None)

        if self.symmetrize:
            unsheared_image = self._symmetrize_noise('gal',
                                                     unsheared_image,
                                                     newpsf_interp,
                                                     Shape(0.0,0.0))


        uobs = self._make_obs(unsheared_image, newpsf)

        return uobs

    def get_obs_psfshear(self, shear):
        """
        This is the case where we shear the psf image, for calculating Rpsf

        parameters
        ----------
        shear: ngmix.Shape
            The shear to apply
        """
        newpsf, newpsf_interp = self.get_target_psf(shear, 'psf_shear')
        conv_image = self.get_target_image(newpsf_interp, shear=None)

        if self.symmetrize:
            conv_image = self._symmetrize_noise('psf',
                                                conv_image,
                                                newpsf_interp,
                                                shear)

        newobs = self._make_obs(conv_image, newpsf)
        return newobs


    def get_target_psf(self, shear, type):
        """
        get galsim interpolated image for dilated, possibly sheared, psf

        parameters
        ----------
        shear: ngmix.Shape
            The applied shear
        type: string
            Type of psf target.  For type='gal_shear', the psf is just dilated to
            deal with noise amplification.  For type='psf_shear' the psf is also
            sheared for calculating Rpsf

        returns
        -------
        galsim image object
        """
        import galsim

        _check_shape(shear)

        g1abs = abs(shear.g1)
        g2abs = abs(shear.g2)
        psf_grown_nopix = self.gs_psf_int_nopix.dilate(1 + 2*max([g1abs,g2abs]))

        psf_grown_interp = galsim.Convolve(psf_grown_nopix,self.pixel)

        if type=='psf_shear':
            # eric remarked that he thought we should shear the pixelized version
            psf_grown_interp = psf_grown_interp.shear(g1=shear.g1, g2=shear.g2)

        psf_grown_image = galsim.ImageD(self.gs_psf_image.bounds)

        # TODO not general, using just pixel scale
        psf_grown_interp.drawImage(image=psf_grown_image,
                                   scale=self.pixel_scale,
                                   method='no_pixel')

        return psf_grown_image, psf_grown_interp

    def get_target_image(self, psf_interp, shear=None):
        """
        get the target image, convolved with the specified psf
        and possibly sheared

        This is where whitening happens

        parameters
        ----------
        psf: A galsim interpolated image
            psf by which to convolve
        shear: ngmix.Shape, optional
            The shear to apply

        returns
        -------
        galsim image object
        """
        import galsim
        if shear is not None:
            shim_interp_nopsf = self.get_sheared_image_interp_nopsf(shear)
        else:
            shim_interp_nopsf = self.gs_image_int_nopsf

        #psfint = galsim.InterpolatedImage(psf, x_interpolant = self.l5int)
        imconv = galsim.Convolve([shim_interp_nopsf, psf_interp])

        # Draw reconvolved, sheared image to an ImageD object, and return.
        # pixel is already in the interpolated psf image
        newim = galsim.ImageD(self.gs_image.bounds)
        imconv.drawImage(image=newim,
                         method='no_pixel',
                         scale=self.pixel_scale)

        if self.whiten:
            if self.same_seed:
                imconv.noise.rng.reset(self.seed)
            newvar=imconv.noise.whitenImage(newim)

        if self.symmetrize:

        return newim

    def _symmetrize_noise(self, type, image_in, psf_target_interp, shear):
        """
        mostly direct from Eric's code
        """

        image = image_in.copy()

        nrow,ncol=image.array.shape

        g1,g2,g1psf,g2psf=self._get_symmetrize_shapes(type, shear)
        key=self._get_symmetrize_key(g1,g2,g1psf,g2psf,nrow,ncol)

        if key in Metacal.sym_cache:
            image += Metacal.sym_cache[key]
        else:

            GN = galsim.GaussianNoise(sigma=self.med_err)
            test_im = galsim.Image(512,512,scale=self.pixel_scale)
            test_im.addNoise(GN)
            CN = galsim.CorrelatedNoise(test_im, scale=self.pixel_scale)

            # Now apply the same set of operations to this...
            CN = CN.convolvedWith(self.gs_psf_int_inv)

            if type=='gal':
                CN = CN.shear(g1 = g1, g2 = g2)
            else:
                CN = CN.shear(g1 = g1psf, g2 = g2psf)

            CN = CN.convolvedWith(psf_target_interp)

            # this modifies in place
            image.symmetrizeNoise(CN,order=4)
            noise_diff = image - image_in

            Metacal.sym_cache[key] = noise_diff

        return image

    def _get_symmetrize_key(self, g1,g2,g1psf,g2psf,nrow,ncol):
        key = '%s %s %s %s %s %s' % (nrow,ncol,g1,g2,g1psf,g2psf)
        return key

    def _get_symmetrize_shapes(self, type, shear):
        if type=='gal':
            g1psf,g2psf=0.0,0.0
            if shear is None:
                g1,g2=0.0,0.0
            else:
                g1,g2=shear.g1,shear.g2
        else:
            g1,g2=0.0,0.0
            if shear is None:
                g1psf,g2psf=0.0,0.0
            else:
                g1psf,g2psf=shear.g1,shear.g2

        return g1,g2,g1psf,g2psf

    def get_sheared_image_interp_nopsf(self, shear):
        """
        get the image sheared by the reqested amount, pre-psf and pre-pixel

        parameters
        ----------
        shear: ngmix.Shape
            The shear to apply

        returns
        -------
        galsim image object
        """
        _check_shape(shear)
        # this is the interpolated, devonvolved image
        sheared_image = self.gs_image_int_nopsf.shear(g1=shear.g1, g2=shear.g2)
        return sheared_image

    def _set_data(self,
                  obs,
                  lanczos_pars=None,
                  symmetrize=False,
                  whiten=False,
                  same_seed=False):
        """
        create galsim objects based on the input observation
        """
        import galsim

        if not obs.has_psf():
            raise ValueError("observation must have a psf observation set")

        self.obs=obs
        self.symmetrize=symmetrize
        self.whiten=whiten
        self.same_seed=same_seed
        self._set_wcs(obs.jacobian)
        self._set_lanczos(lanczos_pars=lanczos_pars)

        # these would share data with the original numpy arrays, make copies
        # to be sure they don't get modified
        mval=0
        self.gs_image = galsim.Image(obs.image.copy(),
                                     wcs=self.gs_wcs,
                                     xmin=mval,ymin=mval)
        self.gs_psf_image = galsim.Image(obs.psf.image.copy(),
                                         wcs=self.gs_wcs,
                                         xmin=mval,ymin=mval)

        # interpolated psf image
        self.gs_psf_int = galsim.InterpolatedImage(self.gs_psf_image,
                                                   x_interpolant = self.l5int)
        # interpolated psf deconvolved from pixel
        self.gs_psf_int_nopix = galsim.Convolve([self.gs_psf_int, self.pixel_inv])

        # this can be used to deconvolve the psf from the galaxy image
        self.gs_psf_int_inv = galsim.Deconvolve(self.gs_psf_int)

        # interpolated galaxy image, still pixelized
        self.gs_image_int = galsim.InterpolatedImage(self.gs_image,
                                                     x_interpolant=self.l5int)
        if self.whiten or self.symmetrize:
            # TODO constant noise won't work for real data
            med_wt = numpy.median( self.obs.weight )
            self.med_var = 1.0/med_wt
            self.med_err = numpy.sqrt(self.med_var)

        if self.whiten:
            self.gs_image_int.noise = galsim.UncorrelatedNoise(self.med_var)
            if self.same_seed:
                self.seed=numpy.random.randint(0, 2**30-1)

        # deconvolved galaxy image, psf+pixel removed
        self.gs_image_int_nopsf = galsim.Convolve(self.gs_image_int,
                                                  self.gs_psf_int_inv)


    def _set_wcs(self, jacobian):
        """
        create a galsim JacobianWCS from the input ngmix.Jacobian, as
        well as pixel objects
        """
        import galsim

        self.jacobian=jacobian

        # TODO might be reversed row->y or x?
        self.gs_wcs = galsim.JacobianWCS(jacobian.dudrow,
                                         jacobian.dudcol,
                                         jacobian.dvdrow, 
                                         jacobian.dvdcol)

        # TODO how this gets used does not seem general, why not use full wcs
        self.pixel_scale=self.gs_wcs.maxLinearScale()
        self.pixel = galsim.Pixel(self.pixel_scale)
        self.pixel_inv = galsim.Deconvolve(self.pixel)

    def _set_lanczos(self, lanczos_pars=None):
        """
        set the laczos interpolation configuration
        """
        import galsim
        if lanczos_pars is None:
            lanczos_pars=LANCZOS_PARS_DEFAULT
        else:
            for n in ['order','conserve_dc','tol']:
                lanczos_pars[n]=lanczos_pars.get(n,LANCZOS_PARS_DEFAULT[n])

        self.lanczos_pars=lanczos_pars

        self.l5 = galsim.Lanczos(lanczos_pars['order'],
                                 lanczos_pars['conserve_dc'],
                                 lanczos_pars['tol'])
        self.l5int = self.l5
        #self.l5int = galsim.InterpolantXY(self.l5)

    def _make_obs(self, im, psf_im):
        """
        inputs are galsim objects
        """
        obs=self.obs

        psf_obs = Observation(psf_im.array, jacobian=obs.jacobian)

        weight=obs.weight
        newobs=Observation(im.array,
                           jacobian=obs.jacobian,
                           weight=weight,
                           psf=psf_obs)
        return newobs

def _check_shape(shape):
    if not isinstance(shape, Shape):
        raise TypeError("shape must be of type ngmix.Shape")

def jackknife_shear(g, R, Rpsf=None, chunksize=1):
    """
    get the shear metacalibration style

    parameters
    ----------
    g: array
        [N,2] shape measurements
    R: array
        [N,2,2] shape response measurements
    Rpsf: array, optional
        [N,2] psf response
    chunksize: int, optional
        chunksize for jackknifing
    """


    ntot = g.shape[0]

    nchunks = ntot/chunksize

    g_sum = g.sum(axis=0)
    R_sum = R.sum(axis=0)

    if Rpsf is not None:
        Rpsf_sum = Rpsf.sum(axis=0)
        g_sum -= Rpsf_sum

    R_sum_inv = numpy.linalg.inv(R_sum)
    shear = numpy.dot(R_sum_inv, g_sum)


    shears = zeros( (nchunks, 2) )
    for i in xrange(nchunks):

        beg = i*chunksize
        end = (i+1)*chunksize

        tgsum = g[beg:end,:].sum(axis=0)
        tR_sum = R[beg:end,:,:].sum(axis=0)

        if Rpsf is not None:
            tRpsf_sum = Rpsf[beg:end,:].sum(axis=0)
            tgsum -= tRpsf_sum

        j_g_sum = g_sum - tgsum
        j_R_sum = R_sum - tR_sum

        j_R_inv = numpy.linalg.inv(j_R_sum)


        shears[i, :] = numpy.dot(j_R_inv, j_g_sum)

    shear_cov = zeros( (2,2) )
    fac = (nchunks-1)/float(nchunks)

    shear_cov[0,0] = fac*( ((shear[0]-shears[:,0])**2).sum() )
    shear_cov[0,1] = fac*( ((shear[0]-shears[:,0]) * (shear[1]-shears[:,1])).sum() )
    shear_cov[1,0] = shear_cov[0,1]
    shear_cov[1,1] = fac*( ((shear[1]-shears[:,1])**2).sum() )

    out={'shear':shear,
         'shear_cov':shear_cov,
         'g_sum':g_sum,
         'R_sum':R_sum,
         'gsens_sum':R_sum, # another name
         'R_sum_inv':R_sum_inv,
         'nuse':g.shape[0],
         'shears':shears}
    if Rpsf is not None:
        out['Rpsf_sum'] = Rpsf_sum
    return out



def jackknife_shear_weighted(g, gsens, weights, chunksize=1):
    """
    get the shear metacal style

    parameters
    ----------
    g: array
        [N,2] shape measurements
    gsens: array
        [N,2,2] shape sensitivity measurements
    weights: array, optional
        Weights to apply
    chunksize: int, optional
        chunksize for jackknifing
    """

    if weights is None:
        weights=ones(g.shape[0])

    ntot = g.shape[0]

    nchunks = ntot/chunksize

    wsum = weights.sum()
    wa=weights[:,newaxis]
    waa=weights[:,newaxis,newaxis]

    g_sum = (g*wa).sum(axis=0)
    gsens_sum = (gsens*waa).sum(axis=0)

    gsens_sum_inv = numpy.linalg.inv(gsens_sum)
    shear = numpy.dot(gsens_sum_inv, g_sum)

    shears = zeros( (nchunks, 2) )
    for i in xrange(nchunks):

        beg = i*chunksize
        end = (i+1)*chunksize

        wtsa = (weights[beg:end])[:,newaxis]
        wtsaa = (weights[beg:end])[:,newaxis,newaxis]

        tgsum = (g[beg:end,:]*wtsa).sum(axis=0)
        tgsens_sum = (gsens[beg:end,:,:]*wtsaa).sum(axis=0)


        j_g_sum     = g_sum     - tgsum
        j_gsens_sum = gsens_sum - tgsens_sum

        j_gsens_inv = numpy.linalg.inv(j_gsens_sum)

        shears[i, :] = numpy.dot(j_gsens_inv, j_g_sum)

    shear_cov = zeros( (2,2) )
    fac = (nchunks-1)/float(nchunks)

    shear_cov[0,0] = fac*( ((shear[0]-shears[:,0])**2).sum() )
    shear_cov[0,1] = fac*( ((shear[0]-shears[:,0]) * (shear[1]-shears[:,1])).sum() )
    shear_cov[1,0] = shear_cov[0,1]
    shear_cov[1,1] = fac*( ((shear[1]-shears[:,1])**2).sum() )

    return {'shear':shear,
            'shear_cov':shear_cov,
            'g_sum':g_sum,
            'gsens_sum':gsens_sum,
            'gsens_sum_inv':gsens_sum_inv,
            'shears':shears,
            'weights':weights,
            'wsum':wsum,
            'nuse':g.shape[0]}


def bootstrap_shear(g, gpsf, R, Rpsf, nboot, verbose=False):
    """
    get the shear metacalstyle

    The responses are bootstrapped independently of the
    shear estimators

    parameters
    ----------
    g: array
        [N,2] shape measurements
    gpsf: array
        [N,2] shape measurements
    R: array
        [NR,2,2] shape response measurements
    Rpsf: array
        [NR,2] psf response
    nboot: int
        number of bootstraps to do
    """

    ng = g.shape[0]
    nR = R.shape[0]

    # overall mean
    if verbose:
        print("    getting overall mean and naive error")
    res = get_mean_shear(g, gpsf, R, Rpsf)
    if verbose:
        print("    shear:         ",res['shear'])
        print("    shear_err:     ",res['shear_err'])

    # need workspace for ng from both data and
    # deep response data

    g_scratch    = zeros( (ng, 2) )
    gpsf_scratch = zeros( (ng, 2) )
    R_scratch    = zeros( (nR, 2, 2) )
    Rpsf_scratch = zeros( (nR, 2) )

    shears = zeros( (nboot, 2) )

    for i in xrange(nboot):
        if verbose:
            print("    boot %d/%d" % (i+1,nboot))

        g_rind = numpy.random.randint(0, ng, ng)
        R_rind = numpy.random.randint(0, nR, nR)

        g_scratch[:, :]    = g[g_rind, :]
        gpsf_scratch[:, :] = gpsf[g_rind, :]
        R_scratch[:, :, :] = R[R_rind, :, :]
        Rpsf_scratch[:, :] = Rpsf[R_rind, :]

        tres = get_mean_shear(g_scratch,
                              gpsf_scratch,
                              R_scratch,
                              Rpsf_scratch)
        shears[i,:] = tres['shear']

    shear_cov = zeros( (2,2) )

    shear = res['shear']
    shear_mean = shears.mean(axis=0)

    fac = 1.0/(nboot-1.0)
    shear_cov[0,0] = fac*( ((shear[0]-shears[:,0])**2).sum() )
    shear_cov[0,1] = fac*( ((shear[0]-shears[:,0]) * (shear[1]-shears[:,1])).sum() )
    shear_cov[1,0] = shear_cov[0,1]
    shear_cov[1,1] = fac*( ((shear[1]-shears[:,1])**2).sum() )

    res['shear_mean'] = shear_mean
    res['shear_err'] = sqrt(diag(shear_cov))
    res['shear_cov'] = shear_cov
    res['shears'] = shears
    return res

def get_mean_shear(g, gpsf, R, Rpsf):

    g_sum = g.sum(axis=0)
    g_err = g.std(axis=0)/sqrt(g.shape[0])

    g_mean = g_sum/g.shape[0]

    R_sum = R.sum(axis=0)
    R_mean = R_sum/R.shape[0]

    Rpsf_sum = Rpsf.sum(axis=0)
    Rpsf_mean = Rpsf_sum/Rpsf.shape[0]

    psf_corr_arr = gpsf.copy()
    psf_corr_arr[:,0] *= Rpsf_mean[0]
    psf_corr_arr[:,1] *= Rpsf_mean[1]

    psf_corr_sum = psf_corr_arr.sum(axis=0)
    psf_corr = psf_corr_sum/g.shape[0]

    Rinv = linalg.inv(R_mean)

    shear = dot(Rinv, g_mean - psf_corr)
    # naive error
    shear_err = dot(Rinv, g_err)

    return {
            'shear':shear,
            'shear_err':shear_err,
            'g_mean':g_mean,

            'R':R_mean,
            'Rpsf':Rpsf_mean,
            'psf_corr':psf_corr,

            'g_sum':g_sum,
            'R_sum':R_sum,
            'Rpsf_sum':Rpsf_sum,
            'psf_corr_sum':psf_corr_sum,
            'ng': g.shape[0],
            'nR': R.shape[0]
           }

def test():
    import images

    step=0.01
    shear_p0 = Shape(step, 0.0)

    obs, obs_sheared_dilated = _get_sim_obs(shear_p0.g1,shear_p0.g2,
                                           r50=2.0, r50_psf=1.5)

    m=Metacal(obs)
    obs_p0 = m.get_obs_galshear(shear_p0)

    images.compare_images(obs_sheared_dilated.image,
                          obs_p0.image,
                          label1='shear/dilate',
                          label2='metacal',
                          width=1000,
                          height=1000)
    
    '''
    images.compare_images(obs.image,
                          obs_p0.image,
                          label1='unsheared, undilated',
                          label2='metacal',
                          width=1000,
                          height=1000)
    '''

def _get_sim_obs(s1, s2, g1=0.2, g2=0.1, r50=3.0, r50_psf=1.8):
    import galsim

    dims=32,32

    flux=100.0

    g1psf=0.05
    g2psf=-0.07
    fluxpsf=1.0

    s1abs = abs(s1)
    s2abs = abs(s2)
    dilate = 1. + 2.*max([s1abs,s2abs])

    r50_psf_dilated = r50_psf * dilate

    gal0 = galsim.Gaussian(flux=flux, half_light_radius=r50)
    gal0 = gal0.shear(g1=g1, g2=g2)
    gal0_sheared = gal0.shear(g1=s1, g2=s2)

    psf = galsim.Gaussian(flux=fluxpsf, half_light_radius=r50_psf)
    psf = psf.shear(g1=g1psf,g2=g2psf)

    psf_dilated = galsim.Gaussian(flux=fluxpsf, half_light_radius=r50_psf_dilated)
    psf_dilated = psf_dilated.shear(g1=g1psf,g2=g2psf)

    gal = galsim.Convolve([psf, gal0])
    gal_sheared_dilated = galsim.Convolve([psf_dilated, gal0_sheared])

    psf_image = psf.drawImage(nx=dims[1],
                              ny=dims[0],
                              scale=1.0,
                              dtype=numpy.float64)
    psf_image_dilated = psf_dilated.drawImage(nx=dims[1],
                                              ny=dims[0],
                                              scale=1.0,
                                              dtype=numpy.float64)


    image = gal.drawImage(nx=dims[1],
                          ny=dims[0],
                          scale=1.0,
                          dtype=numpy.float64)

    image_sheared_dilated = gal_sheared_dilated.drawImage(nx=dims[1],
                                                          ny=dims[0],
                                                          scale=1.0,
                                                          dtype=numpy.float64)


    psf_obs = Observation(psf_image.array)
    psf_obs_dilated = Observation(psf_image_dilated.array)

    obs = Observation(image.array, psf=psf_obs)
    obs_sheared_dilated = Observation(image_sheared_dilated.array,
                                      psf=psf_obs_dilated)

    return obs, obs_sheared_dilated
