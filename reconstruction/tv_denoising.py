import numpy as np


def div(grad):
    """ Compute divergence of image gradient """
    res = np.zeros(grad.shape[1:])
    for d in range(grad.shape[0]):
        this_grad = np.rollaxis(grad[d], d)
        this_res = np.rollaxis(res, d)
        this_res[:-1] += this_grad[:-1]
        this_res[1:-1] -= this_grad[:-2]
        this_res[-1] -= this_grad[-2]
    return res


def gradient(img):
    """
    Compute gradient of an image

    Parameters
    ===========
    img: ndarray
        N-dimensional image

    Returns
    =======
    gradient: ndarray
        Gradient of the image: the i-th component along the first
        axis is the gradient along the i-th axis of the original
        array img
    """
    shape = [img.ndim, ] + list(img.shape)
    gradient = np.zeros(shape, dtype=img.dtype)
    # 'Clever' code to have a view of the gradient with dimension i stop
    # at -1
    slice_all = [0, slice(None, -1), ]
    for d in range(img.ndim):
        gradient[slice_all] = np.diff(img, axis=d)
        slice_all[0] = d + 1
        slice_all.insert(1, slice(None))
    return gradient


def _projector_on_dual(grad):
    """
    modifies in place the gradient to project it
    on the L2 unit ball
    """
    norm = np.maximum(np.sqrt(np.sum(grad ** 2, 0)), 1.)
    for grad_comp in grad:
        grad_comp /= norm
    return grad


def dual_gap(im, new, gap, weight):
    """
    dual gap of total variation denoising
    see "Total variation regularization for fMRI-based prediction of behavior",
    by Michel et al. (2011) for a derivation of the dual gap
    """
    im_norm = (im ** 2).sum()
    gx, gy = np.zeros_like(new), np.zeros_like(new)
    gx[:-1] = np.diff(new, axis=0)
    gy[:, :-1] = np.diff(new, axis=1)
    if im.ndim == 3:
        gz = np.zeros_like(new)
        gz[..., :-1] = np.diff(new, axis=2)
        tv_new = 2 * weight * np.sqrt(gx ** 2 + gy ** 2 + gz ** 2).sum()
    else:
        tv_new = 2 * weight * np.sqrt(gx ** 2 + gy ** 2).sum()
    dual_gap = (gap ** 2).sum() + tv_new - im_norm + (new ** 2).sum()
    return 0.5 / im_norm * dual_gap


def tv_denoise_fista(im, weight=50, eps=5.e-5, n_iter_max=200,
                     check_gap_frequency=3, val_min=None, val_max=None,
                     verbose=False):
    """
    Perform total-variation denoising on 2-d and 3-d images

    Find the argmin `res` of
        1/2 * ||im - res||^2 + weight * TV(res),

    where TV is the isotropic l1 norm of the gradient.

    Parameters
    ----------
    im: ndarray of floats (2-d or 3-d)
        input data to be denoised. `im` can be of any numeric type,
        but it is cast into an ndarray of floats for the computation
        of the denoised image.

    weight: float, optional
        denoising weight. The greater ``weight``, the more denoising (at
        the expense of fidelity to ``input``)

    eps: float, optional
        precision required. The distance to the exact solution is computed
        by the dual gap of the optimization problem and rescaled by the l2
        norm of the image (for contrast invariance).

    n_iter_max: int, optional
        maximal number of iterations used for the optimization.

    val_min: None or float, optional
        an optional lower bound constraint on the reconstructed image

    val_max: None or float, optional
        an optional upper bound constraint on the reconstructed image

    verbose: bool, optional
        if True, plot the dual gap of the optimization

    Returns
    -------
    out: ndarray
        denoised array

    Notes
    -----
    The principle of total variation denoising is explained in
    http://en.wikipedia.org/wiki/Total_variation_denoising

    The principle of total variation denoising is to minimize the
    total variation of the image, which can be roughly described as
    the integral of the norm of the image gradient. Total variation
    denoising tends to produce "cartoon-like" images, that is,
    piecewise-constant images.

    This function implements the FISTA (Fast Iterative Shrinkage
    Thresholding Algorithm) algorithm of Beck et Teboulle, adapted to
    total variation denoising in "Fast gradient-based algorithms for
    constrained total variation image denoising and deblurring problems"
    (2009).

    For details on implementing the bound constraints, read the Beck and
    Teboulle paper.
    """
    input_img = im
    if not input_img.dtype.kind == 'f':
        input_img = input_img.astype(np.float)
    shape = [input_img.ndim, ] + list(input_img.shape)
    grad_im = np.zeros(shape)
    grad_aux = np.zeros(shape)
    t = 1.
    i = 0
    if input_img.ndim == 2:
        # Upper bound on the Lipschitz constant
        lipschitz_constant = 9
    elif input_img.ndim == 3:
        lipschitz_constant = 12
    else:
        raise ValueError('Cannot compute TV for images that are not '
                         '2D or 3D')
    # negated_output is the negated primal variable in the optimization
    # loop
    negated_output = -input_img
    # Clipping values for the inner loop
    negated_val_min = np.nan
    negated_val_max = np.nan
    if val_min is not None:
        negated_val_min = -val_min
    if val_max is not None:
        negated_val_max = -val_max
    if (val_min is not None or val_max is not None):
        # With bound constraints, the stopping criterion is on the
        # evolution of the output
        negated_output_old = negated_output.copy()
    while i < n_iter_max:
        grad_tmp = gradient(negated_output)
        grad_tmp *= 1. / (lipschitz_constant * weight)
        grad_aux += grad_tmp
        grad_tmp = _projector_on_dual(grad_aux)
        t_new = 1. / 2 * (1 + np.sqrt(1 + 4 * t ** 2))
        t_factor = (t - 1) / t_new
        grad_aux = (1 + t_factor) * grad_tmp - t_factor * grad_im
        grad_im = grad_tmp
        t = t_new
        gap = weight * div(grad_im)
        # Compute the primal variable
        negated_output = gap - input_img
        if (val_min is not None or val_max is not None):
            negated_output = negated_output.clip(negated_val_max,
                                negated_val_min,
                                out=negated_output)
        if (i % check_gap_frequency) == 0:
            if val_min is None and val_max is None:
                # In the case of bound constraints, we don't have
                # the dual gap
                dgap = dual_gap(input_img, -negated_output, gap, weight)
                if verbose:
                    print 'Iteration % 2i, dual gap: % 6.3e' % (i, dgap)
                if dgap < eps:
                    break
            else:
                diff = np.max(np.abs(negated_output_old - negated_output))
                diff /= np.max(np.abs(negated_output))
                if verbose:
                    print 'Iteration % 2i, relative difference: % 6.3e' % (i,
                                diff)
                if diff < eps:
                    break
                negated_output_old = negated_output
        i += 1
    # Compute the primal variable
    output = input_img - gap
    if (val_min is not None or val_max is not None):
        output = output.clip(-negated_val_min, -negated_val_max, out=output)
    return output


def test_grad_div_adjoint(size=12, random_state=42):
    # We need to check that <D x, y> = <x, DT y> for x and y random vectors
    random_state = np.random.RandomState(random_state)

    x = np.random.normal(size=(size, size, size))
    y = np.random.normal(size=(3, size, size, size))

    np.testing.assert_almost_equal(np.sum(gradient(x) * y),
                                   -np.sum(x * div(y)))


if __name__ == '__main__':
    # First our test
    test_grad_div_adjoint()
    from scipy.misc import lena
    import matplotlib.pyplot as plt
    from time import time

    # Smoke test on lena
    l = lena().astype(np.float)
    # normalize image between 0 and 1
    l /= l.max()
    l += 0.1 * l.std() * np.random.randn(*l.shape)
    t0 = time()
    res = tv_denoise_fista(l, weight=2.5, eps=5.e-5, verbose=True)
    t1 = time()
    print t1 - t0
    plt.figure()
    plt.subplot(121)
    plt.imshow(l, cmap='gray')
    plt.subplot(122)
    plt.imshow(res, cmap='gray')

    # Smoke test on a 3D random image with hidden structure
    np.random.seed(42)
    img = np.random.normal(size=(12, 24, 24))
    img[4:8, 8:16, 8:16] += 1.5
    res = tv_denoise_fista(img, weight=.6, eps=5.e-5, verbose=True)
    plt.figure(figsize=(9, 3))
    plt.subplot(131)
    plt.imshow(img[6], cmap='gist_earth')
    plt.title('Original data')
    plt.subplot(132)
    plt.imshow(res[6], cmap='gist_earth', vmin=-.1, vmax=.3)
    plt.title('TV')

    # add constraints
    res_cons = tv_denoise_fista(img, weight=.6, eps=5.e-5, verbose=True,
                           val_min=0, val_max=1.5)
    plt.subplot(133)
    plt.imshow(res_cons[6], cmap='gist_earth', vmin=-.1, vmax=.3)
    plt.title('TV + interval')

    plt.show()
