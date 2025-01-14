'''
Compute the test statistic proposed in change point detection.
Fit distinct models for Q function approximation for different actions
! NOTE: asssum 2 actions, i.e, nactions=2
'''

# Import required libraries
import numpy as np
from sklearn.linear_model import LinearRegression
from collections import namedtuple
from sklearn.preprocessing import PolynomialFeatures
import scipy.sparse as sp
from scipy.stats import multivariate_normal
from copy import copy
from sklearn.kernel_approximation import RBFSampler
# from sklearn.metrics import pairwise_distances
from scipy.spatial.distance import pdist
from joblib import Parallel, delayed
from bisect import bisect_right
import csv

# from . import select_num_basis as cv


# %% fitted Q iteration
class q_learning():
    """
    Q Function approximation via polynomial regression.
    """
    def __init__(self, States, Rewards, Actions, qmodel='rbf', degree=2,
                 gamma=0.95, rbf_dim=5, rbf_bw=1.0, n_actions=2, centered=False, 
                 RBFSampler_random_state=1, States_next = None):
        '''
        initialization
        :param env: an object of RLenv
        :param degree: degree of polynomial basis used for functional approximation of Q function
        :param gamma: discount rate of rewards
        :param time_start: starting time of the interval
        :param time_terminal: terminal time of the interval
        '''

        # self.env = env
        # degree of polynomial basis
        self.degree = degree
        # initial_dsgn = self.create_design_matrix_t(self.featurize_state(initial_states), self.env.Actions[:, time_start])
        # self.model = LinearRegression(fit_intercept = False)#SGDRegressor(learning_rate="constant")
        # self.model = KernelRidge(kernel='rbf')#SGDRegressor(learning_rate="constant")
        self.qmodel = qmodel

        # if no rbf basis, then just a linear term
        if rbf_dim == 0:
            self.qmodel = 'polynomial'
            self.degree = 1

        # if qmodel == 'rbf':
        #     centered = True
        if self.qmodel == "rbf":
            self.featurize = RBFSampler(gamma=rbf_bw, random_state=RBFSampler_random_state, n_components=rbf_dim)
            self.model = LinearRegression(fit_intercept=False)
        elif self.qmodel == "polynomial":
            self.featurize = PolynomialFeatures(degree=self.degree, include_bias=True)#(centered==False)
            self.model = LinearRegression(fit_intercept=False)
        else:
            self.model = None
            pass

        # # get initial states
        # initial_states = np.vstack(States[:, 0, :])
        # # number of features
        # self.p = len(self.featurize_state([initial_states[0, :]])[0])
        self.States = States
        self.Rewards = Rewards
        self.Actions = Actions
        
        self.States_next = States_next
        # self.Rewards_next = Rewards_next
        # self.Actions_next = Actions_next
        # number of unique actions
        if n_actions is None:
            self.n_actions = len(np.unique(Actions))
        else:
            self.n_actions = n_actions

        # create a list of q function models, one for each action
        self.q_function_list = [copy(self.model) for x in range(self.n_actions)]

        # self.model.fit(initial_dsgn, env.Rewards[:, time_start])
        # self.theta = self.model.coef_

        # self.theta = np.zeros(self.p * env.nAction)
        # self.time_start = time_start
        # self.time_terminal = time_terminal
        self.gamma = gamma
        self.N = Actions.shape[0]
        self.T = Actions.shape[1]

        # create a list of indices to indicate which action is taken
        self.action_indices = [np.where(Actions.flatten() == a)[0] for a in range(self.n_actions)]

        # create design matrix for the current states
        # print(self.featurize)
        self.States0 = self.create_design_matrix(States, Actions, type='current', pseudo_actions=None)
        ## create design matrix for the next states
        if States_next is None:
            self.States1 = self.create_design_matrix(States, Actions, type='next', pseudo_actions=0)
        else:
            self.States1 = self.create_design_matrix(States_next, Actions, type='next', pseudo_actions=0)

        # print(len(self.States1), ', ',   self.n_actions)
        # self.States1_action1 = self.create_design_matrix(States, Actions, type='next', pseudo_actions=1)

        # create a list of vectors of rewards
        # self.Rewards_vec = [None for a in range(self.n_actions)]
        # for a in range(self.n_actions):
        #     self.Rewards_vec[a] = Rewards.flatten()[self.action_indices[a]]
        self.Rewards_vec = Rewards.flatten()

        # # number of features in the design matrix for (s,a)
        # self.p = int(self.States0.shape[1] / self.n_actions)


    def featurize_state(self, state):
        """
        Returns the transformed representation for a state.
        """

        if self.qmodel == "polynomial":
            return self.featurize.fit_transform(state)
        elif self.qmodel == "rbf":
            out = self.featurize.fit_transform(state)
            return PolynomialFeatures(degree=1, include_bias=True).fit_transform(out)
        else: # do nothing
            pass

    # def create_sp_design_matrix(self, features, Actions):
    #     """
    #     Create a sparse design matrix phi for functional approximation.
    #     For each action a in the action space, the features phi(States, a) is a Nxp matrix.
    #     phi is composed of combining the columns of phi(States, a), depending on the action taken
    #     :return: an np.array of size N x (p*a)
    #     """
    #     p = features.shape[1]
    #     ## create column indices for the sparse matrix
    #     idx_add = p * np.arange(self.n_actions)
    #     col = np.array([xi + np.arange(p) for xi in idx_add])
    #     col_idx = col[Actions]
    #     col_idx = np.concatenate(col_idx)
    #
    #     ## create row indices for the sparse matrix
    #     row_idx = np.repeat(np.arange(features.shape[0]), p)
    #
    #     # creating sparse matrix
    #     sparseMatrix = sp.csr_matrix((np.concatenate(features), (row_idx, col_idx)),
    #                                  shape=(features.shape[0], p * self.n_actions))
    #     return sparseMatrix


    def create_design_matrix(self, States, Actions, type='current', pseudo_actions=None):
        '''
        Create design matrix of States from time t0 to t1 (both inclusive)
        :param type: 'current' for St or 'next' for S_t+1
        :param pseudo_actions:
        :return:
        '''
        if type == 'current':
            # stack the states by person, and time: S11, ..., S1T, S21, ..., S2T
            if self.States_next is None:
                States_stack = States[:, :-1 or None, :].transpose(2, 0, 1).reshape(States.shape[2], -1).T
            else:
                States_stack = States[:, :, :].transpose(2, 0, 1).reshape(States.shape[2], -1).T
            Actions_stack = Actions.flatten()
            n_actions = self.n_actions #len(np.unique(Actions))
            features = [None for a in range(n_actions)]
            for a in np.unique(Actions_stack):
                a = int(a)
                action_index = np.where(Actions_stack == a)[0]
                features[a] = States_stack[np.where(Actions_stack == a)[0],:]
                features[a] = self.featurize_state(features[a])
        elif type == 'next':
            if self.States_next is None:
                States_stack = States[:, 1:, :].transpose(2, 0, 1).reshape(States.shape[2], -1).T
            else:
                States_stack = States[:, :, :].transpose(2, 0, 1).reshape(States.shape[2], -1).T
            if pseudo_actions is not None:
                # print('sudo')
                # Actions_stack = np.repeat(pseudo_actions, States_stack.shape[0])
                # features = [None for a in range(self.n_actions)]
                # features[pseudo_actions] = States_stack
                features = [States_stack]
                # print('len(features)',len(features),', shape States[:,1;,:]', States[:, 1:, :].shape, ', shape stack: ',  States[:, 1:, :].transpose(2, 0, 1).reshape(States.shape[2], -1).shape)
                for a in range(len(features)):
                    # if len(action_index) > 1:
                    a = int(a)
                    features[a] = self.featurize_state(features[a])
                    # else:
                    #     features[0] = self.featurize_state(features[0])
            else:
                Actions_stack = Actions.flatten()
                features = [None for a in range(self.n_actions)]
                for a in np.unique(Actions_stack):
                    a = int(a)
                    # print('a', a)
                    action_index = np.where(Actions_stack == a)[0]
                    # if len(action_index) > 0:
                        # print('len(action_index)>0')
                    features[a] = States_stack[np.where(Actions_stack == a)[0], :]
                    features[a] = self.featurize_state(features[a])
                # for a in range(len(features)):
    #     features[a] = self.featurize_state(features[a])
        return features



    def fit(self, model=None, max_iter=200, tol=1e-6):
        # initialize error and number of iterations
        err = 1.0
        num_iter = 0

        # initialize parameter theta
        if model is None:
            if self.qmodel == "rbf" or self.qmodel == "polynomial":
                for a in np.unique(self.Actions):
                    a = int(a)
                    # if self.States0[a] is not None:
                    self.q_function_list[a] = LinearRegression(fit_intercept = False)
                    self.q_function_list[a].fit(self.States0[a], self.Rewards_vec[self.action_indices[a]])
                    # q.q_function_list[a] = LinearRegression(fit_intercept = False)
                    # q.q_function_list[a].fit(self.States0[a], self.Rewards_vec[self.action_indices[a]])

                # self.model = LinearRegression(fit_intercept = False)
                # self.model.fit(self.States0, self.Rewards_vec)
        else:
            self.model = model
            for a in np.unique(self.Actions):
                # if self.States0[a] is not None:
                a = int(a)
                self.q_function_list[a] = copy(model)
                # self.q_function_list[a].fit(self.States0[a], self.Rewards_vec[a])

            # is the model initialized?
            try:
                self.model.coef_
            except: # if not initialized
                # self.model.fit(self.States0, self.Rewards_vec)
                for a in np.unique(self.Actions):
                    # if self.States0[a] is not None:
                    a = int(a)
                    self.q_function_list[a].fit(self.States0[a], self.Rewards_vec[self.action_indices[a]])

        ## FQI
        convergence = True
        errors = []
        # loss = []
        predicted_old = [np.zeros(len(self.action_indices[a])) for a in range(self.n_actions)]
        predicted = [np.zeros(len(self.action_indices[a])) for a in range(self.n_actions)]
        while err > tol and num_iter <= max_iter:

            Q_max = np.ones(shape = self.Rewards_vec.shape) * (-999)
            for a in np.unique(self.Actions):
                a = int(a)
                # if self.States0[a] is not None:
                # predict the Q value for the next time and find out the maximum Q values for each episode
                Q_max = np.maximum(self.q_function_list[a].predict(self.States1[0]), Q_max)

            # compute TD target
            td_target = self.Rewards_vec + self.gamma * Q_max
            # update parameter fit
            err = 0.0
            for a in np.unique(self.Actions):
                a = int(a)
                # if self.States0[a] is not None:
                self.q_function_list[a].fit(self.States0[a], td_target[self.action_indices[a]])
                predicted[a] = self.q_function_list[a].predict(self.States0[a])
                err += sum((predicted[a] - predicted_old[a])**2)
            err = np.sqrt(err)
            errors.append(err)
            predicted_old = copy(predicted)
            num_iter += 1
            # print("err=",err)

            # break if exceeds the max number of iterations allowed
            if num_iter > max_iter:
                convergence = False
                break

        ## calculate TD error
        predicted = np.zeros(shape=self.Rewards_vec.shape)
        for a in np.unique(self.Actions):
            a = int(a)
            # if self.States0[a] is not None:
            predicted[self.action_indices[a]] = self.q_function_list[a].predict(self.States0[a])
        Q_max = np.ones(shape=self.Rewards_vec.shape) * (-999)
        # obtain the optimal actions at S_t+1
        opt_action = np.zeros(shape=self.Rewards_vec.shape, dtype='int32')
        for a in np.unique(self.Actions):
            a = int(a)
            # if self.States0[a] is not None:
            # predict the Q value for the next time and find out the maximum Q values for each episode
            Q_a = self.q_function_list[a].predict(self.States1[0])
        # should we update the optimal action?
            better_action_indices = np.where(Q_a > Q_max)
            opt_action[better_action_indices] = a
            Q_max[better_action_indices] = Q_a[better_action_indices]
            # Q_max = np.maximum(Q_a, Q_max)

        td_error = self.Rewards_vec + self.gamma * Q_max - predicted

        ## calculate W matrix
        # create design matrix for the states under the optimal actions

        # optimal_design_matrix_list = self.create_design_matrix(self.States, opt_action, 'next')
        # optimal_design_matrix = np.zeros(shape = self.States1[0].shape)
        # for a in range(self.n_actions):
        #     optimal_design_matrix[self.action_indices[a],:] = optimal_design_matrix_list[a]

        # W_mat = 0.0
        # for a in range(self.n_actions):
        #     W_mat += self.States0[a].T.dot(self.States0[a] - self.gamma * optimal_design_matrix_list[a]) / self.T
        # W_mat = self.States0.T.dot(self.States0 - self.gamma * optimal_design_matrix) / self.T

        FQI_result = namedtuple("beta", ["q_function_list", "design_matrix", 'Qmodel'])
        return FQI_result(self.q_function_list, self.States0,
                          [errors, num_iter, convergence])


    def optimal(self):
        Actions0 = np.zeros(self.Actions.shape, dtype='int32')
        design_matrix0 = self.create_design_matrix(self.States, Actions0, type='current', pseudo_actions=None)
        opt_reward = np.ones(shape=(Actions0.shape[0] * Actions0.shape[1], 1)) * (-999)
        opt_action = np.zeros(shape = self.Actions.shape, dtype = 'int32')
        for a in np.unique(self.Actions):
            a = int(a)
            # if self.States0[a] is not None:
            q_estimated0_a = self.q_function_list[a].predict(design_matrix0[0])
            # should we update the optimal action?
            better_action_indices = np.where(q_estimated0_a > opt_reward)
            opt_action[better_action_indices] = a
            opt_reward = np.maximum(opt_reward, q_estimated0_a)

        # q_estimated0 = self.model.predict(design_matrix0)
        #
        # Actions0 = np.ones(self.Actions.shape, dtype='int32')
        # design_matrix0 = self.create_design_matrix(self.States, Actions0, type='current', pseudo_actions=None)
        # q_estimated1 = self.model.predict(design_matrix0)
        #
        # opt_reward = np.maximum(q_estimated0, q_estimated1)
        # opt_action = np.argmax(np.vstack((q_estimated0, q_estimated1)), axis=0)
        optimal = namedtuple("optimal", ["opt_reward", "opt_action"])
        return optimal(opt_reward, opt_action)


    def predict(self, States):
        N = States.shape[0]
        T = States.shape[1] - 1
        Actions0 = np.zeros(shape=(N,T), dtype='int32')
        # print("States =", States)
        # print("Actions0 =", Actions0)
        design_matrix0 = self.create_design_matrix(States, Actions0, type='current', pseudo_actions=None)
        # print("design_matrix0=", design_matrix0)
        # print(design_matrix0[0,:].toarray())
        opt_reward = np.ones(shape = (N*T,)) * (-999)
        opt_action = np.zeros(shape = (N*T,), dtype = 'int32')
        for a in np.unique(self.Actions):
            a = int(a)
            # if self.States0[a] is not None:
            q_estimated0_a = self.q_function_list[a].predict(design_matrix0[0])
            # print(q_estimated0_a)
            # should we update the optimal action?
            better_action_indices = np.where(q_estimated0_a > opt_reward)
            opt_action[better_action_indices] = a
            # opt_action = np.argmax(np.vstack((opt_reward, q_estimated0_a)), axis=0)
            opt_reward = np.maximum(opt_reward, q_estimated0_a)
        optimal = namedtuple("optimal", ["opt_reward", "opt_action"])
        return optimal(opt_reward, opt_action)

#%%
def split_train_test(n, fold = 5):
    '''
    split data into n-fold training and test data
    :param n: sample size of the original data
    :param fold: integer, number of folds
    :return: a list of nfold elements, each element is a list of indices
    '''
    seq = np.random.permutation(n)
    """Yield n number of sequential chunks from seq."""
    d, r = divmod(n, fold)
    for i in range(fold):
        si = (d + 1) * (i if i < r else r) + d * (0 if i < r else i - r)
        yield seq[si:si + (d + 1 if i < r else d)]

def gaussian_rbf_distance(x1, x2, bandwidth = 1.0):
    return np.exp(- bandwidth * np.sum((x1 - x2) ** 2))

def train_test(States, Rewards, Actions, test_index, num_basis, u, bandwidth = 1.0,
          qmodel='rbf', gamma=0.95, model=None, max_iter=300, tol=1e-2, criterion = 'ls'):
    n_actions = len(np.unique(Actions))
    #%% training
    # extract training data
    States_train = np.delete(States, (test_index), axis=0)
    Rewards_train = np.delete(Rewards, (test_index), axis=0)
    Actions_train = np.delete(Actions, (test_index), axis=0)

    def train_test_one_side(States0, Rewards0, Actions0):
        #%% training
        # extract training data
        States_train = np.delete(States0, (test_index), axis=0)
        Rewards_train = np.delete(Rewards0, (test_index), axis=0)
        Actions_train = np.delete(Actions0, (test_index), axis=0)

        q = q_learning(States_train, Rewards_train, Actions_train, qmodel, num_basis,
                       gamma, num_basis, bandwidth, n_actions)
        # States1 = q.States1[0]
        # FQI
        q_fit = q.fit(model)

        # %% testing
        States_test = States0[test_index, :, :]
        Rewards_test = Rewards0[test_index, :]
        Actions_test = Actions0[test_index, :]
        q_test = q_learning(States_test, Rewards_test, Actions_test, qmodel, num_basis,
                            gamma, num_basis, bandwidth)
        # calculate temporal difference error
        Q_max = np.ones(shape=q_test.Rewards_vec.shape) * (-999)
        for a in range(n_actions):
            # predict the Q value for the next time and find out the maximum Q values for each episode
            Q_max = np.maximum(q.q_function_list[a].predict(q_test.States1[0]), Q_max)
        # compute TD target
        td_target = q_test.Rewards_vec + gamma * Q_max

        predicted = np.zeros(shape=q_test.Rewards_vec.shape)
            # [np.zeros(len(q_test.action_indices[a])) for a in range(n_actions)]
        for a in range(n_actions):
            predicted[q_test.action_indices[a]] = q.q_function_list[a].predict(q_test.States0[a])

        # temporal difference error
        tde = q_test.Rewards_vec + gamma * Q_max - predicted

        # calculate loss depending on convergence criterion
        if criterion == 'ls': # least squares
            loss = np.mean(tde ** 2)
        elif criterion == 'kerneldist': # kernel distance
            def distance_function_state(x1,x2):
                return gaussian_rbf_distance(x1, x2, bandwidth)
            def distance_function_action(x1,x2):
                return abs(x1 - x2)
            def tde_product(x1, x2):
                return x1 * x2

            States_stack = States_test[:,:-1,:].transpose(2, 0, 1).reshape(States.shape[2], -1).T
            nrow1 = States_stack.shape[0]
            Actions_vec = Actions_test.flatten()
            K_states = pdist(States_stack, metric=distance_function_state)
            K_actions = pdist(Actions_vec.reshape(-1, 1), metric=distance_function_action)
            tdes = pdist(tde.reshape(-1, 1), metric=tde_product)
            K_total = np.sum((1.0 + K_actions + K_states + K_actions * K_states) * tdes)
            loss = K_total / len(tdes)
        return loss

    # first piece
    States0 = States[:, :(u + 1), :]
    Rewards0 = Rewards[:, :u]
    Actions0 = Actions[:, :u]
    loss = train_test_one_side(States0, Rewards0, Actions0)

    # second piece
    States0 = States[:, u:, :]
    Rewards0 = Rewards[:, u:]
    Actions0 = Actions[:, u:]
    loss += train_test_one_side(States0, Rewards0, Actions0)

    return loss


def select_num_basis_cv(States, Rewards, Actions, u, num_basis_list=[0,1,2,3], bandwidth = 1.0,
                        qmodel='rbf', gamma=0.95, model=None, max_iter=300, tol=1e-4,
                        nfold = 5, num_threads = 5, criterion = 'ls', seed=0):
    np.random.seed(seed)
    N = Rewards.shape[0]
    test_indices = list(split_train_test(N, nfold))
    # random_states = np.random.randint(np.iinfo(np.int32).max, size=n_vectors)

    T = Rewards.shape[1]
    if N*T*States.shape[2] > 100000:
        num_threads = 1
    else:
        num_threads = 4

    min_test_error = 500.0
    selected_num_basis = num_basis_list[0]
    for num_basis in num_basis_list:

        def run_one(fold):
            return train_test(States, Rewards, Actions, test_indices[fold], num_basis, u,
                                 bandwidth, qmodel, gamma, model, max_iter, tol, criterion)

        # parallel jobs
        test_errors = Parallel(n_jobs=num_threads, prefer="threads")(delayed(run_one)(fold) for fold in range(nfold))
        test_error = np.mean(test_errors)
        print(test_error)

        # get the mse of the least square loss in the last iteration
        if test_error < min_test_error:
            min_test_error = test_error
            selected_num_basis = num_basis

    # find the minimum mse
    basis = namedtuple("basis", ["num_basis", "test_error"])
    return basis(selected_num_basis, test_error)




#%%
def pvalue(States, Rewards, Actions, T_total,
           qmodel = 'rbf', degree=4, rbf_dim = 5, rbf_bw = 1.0,
           gamma=0.95, u_list=None, num_changept=3, num_threads=1,
           theta=0.5, J=10, epsilon=0.02, nB=1000,
           select_basis = False, select_basis_interval = 10, num_basis_list=[1,2,3],
           criterion = 'ls', seed = 0, RBFSampler_random_state = 1):
    np.random.seed(seed)

    ## get dimensions
    N = Actions.shape[0]
    T = Actions.shape[1]
    p_state = States.shape[2]
    n_actions = len(np.unique(Actions))

    # calculate the range of u
    # create a list of candidate change points
    if u_list is None:
        if (0.5*T <= epsilon * T_total):
            print('kappa should be greater than 2*epsilon*T')
            return
        u_list = np.linspace(epsilon * T_total, T - epsilon * T_total, num_changept)
        u_list = np.unique([int(i) for i in u_list])
        u_list = np.ndarray.tolist(u_list)

    # get a list of u at which basis selection will be performed
    if select_basis:  # if we perform basis selection:
        print("Performing basis selection")
        u_select_basis = u_list[::select_basis_interval]

        # Creating an empty list
        u_num_basis = []

        if N > 100:  # if sample size is too large
            sample_subject_index = np.random.choice(N, 100, replace=False)
        else:
            sample_subject_index = np.arange(N)
        ### compute bandwidth
        # compute pairwise distance between states for the first piece
        pw_dist = pdist(States[sample_subject_index, :, :].transpose(2, 0, 1).reshape(p_state, -1).T,
                                     metric='euclidean')
        rbf_bw = 1.0 / np.nanmedian(np.where(pw_dist > 0, pw_dist, np.nan))
        # use the median of the minimum of distances as bandwidth
        # rbf_bw = np.median(np.where(pw_dist > 0, pw_dist, np.inf).min(axis=0))
        print("Bandwidth chosen: {:.5f}".format(rbf_bw))
        del pw_dist

        for u in u_select_basis:
            print("u =", u)
           # perform basis selection
            basis = select_num_basis_cv(States[sample_subject_index, :, :],
                                        Rewards[sample_subject_index, :],
                                        Actions[sample_subject_index, :], u, num_basis_list, rbf_bw,
                                        qmodel, gamma, model=None, max_iter=400, tol=1e-4, nfold=5,
                                        num_threads=num_threads*5, criterion=criterion, seed=seed)
            degree = rbf_dim = basis.num_basis
            print("Number of basis chosen:", rbf_dim)
            u_num_basis.append(rbf_dim)
            del basis


        # save to csv file
        with open('selected_basis_dim.csv', "w") as f:
            writer = csv.writer(f)
            writer.writerows([u_select_basis, u_num_basis])


    else: # if we do not perform basis selection, then use the default for both pieces
        fqi_model = q_learning(States, Rewards, Actions, qmodel, degree, gamma, rbf_dim, rbf_bw)
        fqi_model_fit = fqi_model.fit()
        model = copy(fqi_model.model)
        # # initialize model parameters with 0 responses
        # model.fit(fqi_model.States0, fqi_model.Rewards_vec)

    # update the test statistic and the boostrapped test statistic
    noise = np.random.normal(size=N*T*nB).reshape(N*T, nB)

    # first argument: [u_list, random_state]
    def test_u(condition, degree, rbf_dim):
        u_list = condition[0]
        random_state = condition[1]
        rng = np.random.RandomState(random_state)
        print('Calculating ST at time points', u_list, '\n')

        if not select_basis:  # if we perform basis selection:
            # model for Q on [T-kappa, T-u]
            model1 = copy(model)
            # model for Q on [T-u, T]
            model2 = copy(model)

        # initialize test statistic
        ST = 0.0
        BT = np.zeros(nB)

        # initialize normalized test statistic
        ST_normalized = 0.0
        BT_normalized = np.zeros(nB)

        # initialize integral type test statistic
        ST_int = 0.0
        BT_int = np.zeros(nB)

        # initialize integral type test statistic wrt empirical distribution
        ST_int_emp = 0.0
        BT_int_emp = np.zeros(nB)

        # compute test statistic for each u
        # basis_old = u_num_basis[0]
        for u in u_list:
            if select_basis:
                u_select_basis_idx = bisect_right(u_select_basis, u)-1
                degree = rbf_dim = u_num_basis[u_select_basis_idx]
                # model1 = None
                # model2 = None
                if u == u_list[0]: # in the first iteration
                    model1 = None
                    model2 = None
                    basis_old = degree
                else: # after the first iteration
                    if basis_old == degree: # if the current basis is the same as the previous one
                        pass
                    else:
                        model1 = None
                        model2 = None
                        basis_old = degree
            # degree = rbf_dim
            try:
                States0 = States[:, :(u + 1), :]
                Rewards0 = Rewards[:, :u]
                Actions0 = Actions[:, :u]
                fqi_model1 = q_learning(States0, Rewards0, Actions0, qmodel, degree, gamma, rbf_dim, rbf_bw, n_actions)
                out1 = fqi_model1.fit(model=model1, max_iter=400, tol=1e-6)
                # if the model did not converge, skip this and reset starting model
                if out1.Qmodel[0][-1] > 5:
                    print('\nModel diverges at u =', u, 'on Q[ 0,', u, ']. Qerror =', out1.Qmodel[0])
                    # reset model to default if the previous u does not converge
                    if select_basis:
                        model1 = None
                    else:
                        model1 = copy(model)
                    continue
                else:
                    model1 = fqi_model1.model
                    W1_mat = out1.W_mat.todense()
                    factor = (u * (T - u) / T) ** theta



                fqi_model1 = q_learning(States[:,:(u+1),:], Rewards[:,:u], Actions[:,:u], qmodel, degree, gamma, rbf_dim, rbf_bw, n_actions)
                fqi_model2 = q_learning(States[:,u:,:], Rewards[:,u:], Actions[:,u:], qmodel, degree, gamma, rbf_dim, rbf_bw, n_actions)

                out1 = fqi_model1.fit(model=model1, max_iter=400, tol=1e-6)
                out2 = fqi_model2.fit(model=model2, max_iter=400, tol=1e-6)

                # if the model did not converge, skip this and reset starting model
                if out1.Qmodel[0][-1] > 5:
                    print('\nModel diverges at u =', u, 'on Q[ 0,', u, ']. Qerror =', out1.Qmodel[0])
                    # reset model to default if the previous u does not converge
                    if select_basis:
                        model1 = None
                    else:
                        model1 = copy(model)
                    continue
                else:
                    model1 = fqi_model1.model
                if out2.Qmodel[0][-1] > 5:
                    print('\nModel diverges at u =', u, 'on Q[', u, ',', T, ']. Qerror =', out2.Qmodel[0])
                    if select_basis:
                        model2 = None
                    else:
                        model2 = copy(model)
                    continue
                else:
                    model2 = fqi_model2.model

                W1_mat = out1.W_mat.todense()
                W2_mat = out2.W_mat.todense()
                factor = (u * (T - u) / T) ** theta

                ## construct test
                try:
                    # print("u=",u)
                    design_matrix1 = out1.design_matrix
                    td_error1 = out1.td_error
                    design_matrix2 = out2.design_matrix
                    td_error2 = out2.td_error


                    # if number of grid points is too large, need to split to conserve memory
                    # obtain quantile of states
                    quants = [np.quantile(States, 0.05, axis=[0, 1]), np.quantile(States, 0.95, axis=[0, 1])]
                    # max number of grid points per group
                    n_grids = int(20000)
                    # number of features in the design matrix of one action
                    p = int(design_matrix1.shape[1] / n_actions)
                    # number of groups of grid points
                    n_grid_groups = int(np.floor(J*p_state / n_grids))
                    # for the remaining number of grids
                    n_remaining_grid = int(J - n_grids / p_state * n_grid_groups)

                    # compute variance
                    ephi1 = design_matrix1.multiply(td_error1.reshape(-1, 1))
                    ephi2 = design_matrix2.multiply(td_error2.reshape(-1, 1))
                    middle1 = np.linalg.solve(W1_mat, ephi1.toarray().T)
                    middle2 = np.linalg.solve(W2_mat, ephi2.toarray().T)
                    middle = middle1 @ middle1.T / (u ** 2) + middle2 @ middle2.T / ((T - u) ** 2)
                    del ephi1, ephi2
                    def quadratic1(x):
                        return x.dot(middle[:p, :p]) @ x
                    def quadratic2(x):
                        return x.dot(middle[p:, p:]) @ x

                    #%% max type test statistic
                    ST_u = 0.0
                    BT_u = np.zeros(nB)
                    ST_u_normalized = 0.0
                    BT_u_normalized = np.zeros(nB)
                    for n_grid_group in range(n_grid_groups+1):
                        if n_grid_group == n_grid_groups: # compute over remaining grids in the last iteration
                            n_grids = n_remaining_grid
                        if n_grids > 0:
                            ## create list of grids
                            States_grid = rng.uniform(low=quants[0], high=quants[1], size=(n_grids, p_state))
                            if rbf_dim == 0 or degree == 0:
                                States_grid_model = PolynomialFeatures(degree=1, include_bias=True).fit_transform(
                                    States_grid)
                            else:
                                if qmodel == "rbf":
                                    States_grid_model = RBFSampler(gamma=rbf_bw, random_state=RBFSampler_random_state,
                                                                   n_components=rbf_dim).fit_transform(States_grid)
                                    States_grid_model = PolynomialFeatures(degree=1, include_bias=True).fit_transform(
                                        States_grid_model)
                                elif qmodel == "polynomial":
                                    States_grid_model = PolynomialFeatures(degree=degree, include_bias=True).fit_transform(
                                        States_grid)
                                else:
                                    pass
                            del States_grid
                            ## compute unnormalized test statistic
                            # action 0
                            States_grid_action = sp.hstack(
                                (sp.csr_matrix(States_grid_model), sp.csr_matrix((States_grid_model.shape))))
                            abs_diff_action0 = abs(
                                model1.predict(States_grid_action) - model2.predict(States_grid_action))
                            ST_u = max(ST_u, max(abs_diff_action0))
                            # print("n_grid_group=", n_grid_group)
                            # print("ST_u=", ST_u)
                            # action 1
                            States_grid_action = sp.hstack(
                                (sp.csr_matrix(States_grid_model.shape), sp.csr_matrix(States_grid_model)))
                            abs_diff_action1 = abs(
                                model1.predict(States_grid_action) - model2.predict(States_grid_action))
                            ST_u = max(ST_u, max(abs_diff_action1))
                            # print("ST_u=", ST_u)

                            ## construct bootstrapped test
                            error1 = td_error1 * noise[0:u * N, :].T
                            error2 = td_error2 * noise[N * u:N * T, :].T
                            phi1 = np.linalg.solve(W1_mat,  # + np.diag(np.repeat(1e-6, p * fqi_model.n_actions))
                                                   design_matrix1.T.dot(error1.T)) / u
                            phi2 = np.linalg.solve(W2_mat,  # + np.diag(np.repeat(1e-6, p * fqi_model.n_actions))
                                                   design_matrix2.T.dot(error2.T)) / (T - u)
                            del error1, error2
                            # action 0
                            BT_u_action0_unnormalized = abs(States_grid_model @ (phi1[:p, :] - phi2[:p, :]))
                            BT_u = np.maximum(BT_u, np.max(BT_u_action0_unnormalized, axis=0))
                            # action 1
                            BT_u_action1_unnormalized = abs(States_grid_model @ (phi1[p:, :] - phi2[p:, :]))
                            BT_u = np.maximum(BT_u, np.max(BT_u_action1_unnormalized, axis=0))


                            #%% compute normalized test statistic
                            # sd of action 0
                            sd0 = np.sqrt(np.apply_along_axis(quadratic1, 1, States_grid_model))
                            # max over action 0
                            ST_u_normalized = max(ST_u_normalized, np.max(abs_diff_action0 / sd0))
                            # sd of action 1
                            sd1 = np.sqrt(np.apply_along_axis(quadratic2, 1, States_grid_model))
                            # max over action 1
                            ST_u_normalized = max(ST_u_normalized, np.max(abs_diff_action1 / sd1))
                            ## bootstrap
                            BT_u_normalized = np.maximum(np.max((BT_u_action0_unnormalized.T / sd0).T, axis=0),
                                                                  np.max((BT_u_action1_unnormalized.T / sd1).T, axis=0),
                                                                  BT_u_normalized)

                    del States_grid_model, States_grid_action, sd0, sd1, BT_u_action0_unnormalized, BT_u_action1_unnormalized
                    ST_u *= factor
                    BT_u *= factor
                    ST_u_normalized *= factor
                    BT_u_normalized *= factor

                    #%% compute integral type test statistic
                    # max number of grid points per group
                    n_grids = int(20000)
                    ST_u_int = 0.0
                    BT_u_int = np.zeros(nB)
                    for n_grid_group in range(n_grid_groups+1):
                        if n_grid_group == n_grid_groups: # compute over remaining grids in the last iteration
                            n_grids = n_remaining_grid
                        if n_grids > 0:

                            # approximate the reference distribution q* with a multivariate normal distribution of state vectors
                            q_mean = np.mean(States, axis=(0,1))
                            if States.shape[2] == 1: # if state space is 1-dimensional
                                q_cov = np.sqrt(np.var(np.concatenate(States[:,:,0])))
                                # generate random variables from the reference distribution
                                States_ref = np.random.normal(q_mean, q_cov, n_grids)[..., np.newaxis]
                            else: # if state space is 2 or more-dimensional
                                q_cov = np.cov(np.concatenate(States, axis=0).T)
                                States_ref = multivariate_normal.rvs(mean=q_mean, cov=q_cov, size=n_grids, random_state=random_state)

                            # convert grids to design matrix
                            if rbf_dim == 0 or degree == 0:
                                States_ref_model = PolynomialFeatures(degree=1, include_bias=True).fit_transform(States_ref)
                            else:
                                if qmodel == "rbf":
                                    States_ref_model = RBFSampler(gamma=rbf_bw, random_state=RBFSampler_random_state, n_components=rbf_dim).fit_transform(States_ref)
                                    States_ref_model = PolynomialFeatures(degree=1, include_bias=True).fit_transform(States_ref_model)
                                elif qmodel == "polynomial":
                                    States_ref_model = PolynomialFeatures(degree=degree, include_bias=True).fit_transform(States_ref)
                                else:
                                    pass
                            del States_ref

                            ## test stat: integration wrt normal distribution
                            # action 0
                            States_ref_action = sp.hstack((sp.csr_matrix(States_ref_model), sp.csr_matrix((States_ref_model.shape))))
                            abs_diff_action0 = np.sum(abs(model1.predict(States_ref_action) - model2.predict(States_ref_action)))
                            # action 1
                            States_ref_action = sp.hstack((sp.csr_matrix((States_ref_model.shape)), sp.csr_matrix(States_ref_model)))
                            abs_diff_action1 = np.sum(abs(model1.predict(States_ref_action) - model2.predict(States_ref_action)))
                            ST_u_int += (abs_diff_action0 + abs_diff_action1)

                            ## bootstrap
                            BT_u_int += np.sum(abs(States_ref_model @ (phi1[p:, :] - phi2[p:, :])), axis=0) + \
                                       np.sum(abs(States_ref_model @ (phi1[p:, :] - phi2[p:, :])), axis=0)

                    ST_u_int /= (J*n_actions / factor)
                    BT_u_int /= (J*n_actions / factor)
                    del States_ref_model


                    # %% compute integral type test statistic wrt empirical distribution
                    ST_u_int_emp = np.mean(abs(model1.predict(fqi_model1.create_design_matrix(States, Actions, type='current', pseudo_actions=None)) -
                                               model2.predict(fqi_model2.create_design_matrix(States, Actions, type='current', pseudo_actions=None)))) * factor

                    BT_u_int_emp = np.mean(abs(
                        fqi_model1.create_design_matrix(States, Actions, type='current', pseudo_actions=None) @ phi1 -
                        fqi_model2.create_design_matrix(States, Actions, type='current', pseudo_actions=None) @ phi2),
                        axis=0)
                    BT_u_int_emp *= factor

                except:
                    ST_u = 0.0
                    BT_u = np.zeros(nB)

                    ST_u_normalized = 0.0
                    BT_u_normalized = np.zeros(nB)

                    ST_u_int = 0.0
                    BT_u_int = np.zeros(nB)

                    ST_u_int_emp = 0.0
                    BT_u_int_emp = np.zeros(nB)

                    print("ST_u = 0 at u = ", u)

                    # print out large values of BT_u
                if max(BT_u) > 100:
                    print('\nLarge BT_u at u =', u, ", max BT_u =", max(BT_u), '\n')
                    print('Action 0 beta =', out1.beta)
                    print('Action 1 beta =', out2.beta)

                if max(BT_u_normalized) > 300:
                    print('\nLarge BT_u_normalized at u =', u, ", max BT_u_normalized =", max(BT_u_normalized), '\n')
                    print('Action 0 beta =', out1.beta)
                    print('Action 1 beta =', out2.beta)

                if max(BT_u_int) > 100:
                    print('\nLarge BT_u_int at u =', u, ", max BT_u_int =", max(BT_u_int), '\n')
                    print('Action 0 beta =', out1.beta)
                    print('Action 1 beta =', out2.beta)

                # take the max of ST_u and ST
                ST = max(ST_u, ST)
                ST_normalized = max(ST_u_normalized, ST_normalized)
                ST_int = max(ST_u_int, ST_int)
                ST_int_emp = max(ST_u_int_emp, ST_int_emp)
                BT = np.maximum(BT, BT_u)
                BT_normalized = np.maximum(BT_normalized, BT_u_normalized)
                BT_int = np.maximum(BT_int, BT_u_int)
                BT_int_emp = np.maximum(BT_int_emp, BT_u_int_emp)

            except:
                print('Model fails at u=', u, '\n')

        print('\nDone with calculating ST at time points', u_list, '\n')

        return ST, BT, ST_normalized, BT_normalized, ST_int, BT_int, ST_int_emp, BT_int_emp
    ## end function ##


    ### create parallel jobs
    # if multi-threading
    if num_threads > 1:

        def split(seq, n):
            """Yield n number of sequential chunks from l."""
            d, r = divmod(len(seq), n)
            for i in range(n):
                si = (d + 1) * (i if i < r else r) + d * (0 if i < r else i - r)
                yield seq[si:si + (d + 1 if i < r else d)]

        np.random.seed(seed)
        time_list = list(split(u_list, num_threads))
        # generate random states
        random_states = np.random.randint(np.iinfo(np.int32).max, size=num_threads)
        conditions = list(zip(time_list, random_states))
        # parallel jobs
        tests = Parallel(n_jobs=num_threads, prefer="threads")(delayed(test_u)(condition, degree, rbf_dim) for condition in conditions)
        print("Done Multi-threading!")

        # obtain the max of ST and BT over all threads
        ST = 0.0
        BT = np.zeros(nB)
        ST_normalized = 0.0
        BT_normalized = np.zeros(nB)
        ST_int = 0.0
        BT_int = np.zeros(nB)
        ST_int_emp = 0.0
        BT_int_emp = np.zeros(nB)
        for nthread in range(num_threads):
            ST = np.maximum(ST, tests[nthread][0])
            BT = np.maximum(BT, tests[nthread][1])
            ST_normalized = np.maximum(ST_normalized, tests[nthread][2])
            BT_normalized = np.maximum(BT_normalized, tests[nthread][3])
            ST_int = np.maximum(ST_int, tests[nthread][4])
            BT_int = np.maximum(BT_int, tests[nthread][5])
            ST_int_emp = np.maximum(ST_int_emp, tests[nthread][6])
            BT_int_emp = np.maximum(BT_int_emp, tests[nthread][7])

    else:
        ST, BT, ST_normalized, BT_normalized, ST_int, BT_int, ST_int_emp, BT_int_emp = test_u((u_list, seed), degree, rbf_dim)


    test_stats = namedtuple('test_states', ['ST', 'BT', 'ST_normalized', 'BT_normalized', 'ST_int', 'BT_int', 'ST_int_emp', 'BT_int_emp'])
    return test_stats(ST, BT, ST_normalized, BT_normalized, ST_int, BT_int, ST_int_emp, BT_int_emp)

