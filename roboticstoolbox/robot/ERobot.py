#!/usr/bin/env python3
"""
Created on Tue Apr 24 15:48:52 2020
@author: Jesse Haviland
"""

from os.path import splitext
import tempfile
import subprocess
import webbrowser
from numpy import (
    array,
    ndarray,
    isnan,
    zeros,
    eye,
    expand_dims,
    empty,
    concatenate,
    cross,
    arccos,
    dot,
)
from numpy.linalg import norm as npnorm, inv
from spatialmath import SE3, SE2
from spatialgeometry import Cylinder
from spatialmath.base.argcheck import getvector, islistof
from roboticstoolbox.robot.Link import Link, Link2, BaseLink
from roboticstoolbox.robot.ETS import ETS, ETS2
from roboticstoolbox.robot.ET import ET
from roboticstoolbox.robot.DHRobot import DHRobot
from roboticstoolbox.tools import xacro
from roboticstoolbox.tools import URDF
from roboticstoolbox.robot.Robot import Robot
from roboticstoolbox.robot.Gripper import Gripper
from roboticstoolbox.tools.data import rtb_path_to_datafile
from roboticstoolbox.tools.params import rtb_get_param
from pathlib import PurePosixPath
from ansitable import ANSITable, Column
from spatialmath import (
    SpatialAcceleration,
    SpatialVelocity,
    SpatialInertia,
    SpatialForce,
)
from functools import lru_cache
from typing import Union, overload, Dict, List, Tuple, Optional
from copy import deepcopy

ArrayLike = Union[list, ndarray, tuple, set]


class BaseERobot(Robot):

    """
    Construct an ERobot object
    :param et_list: List of elementary transforms which represent the robot
        kinematics
    :type et_list: ET list
    :param name: Name of the robot
    :type name: str, optional
    :param manufacturer: Manufacturer of the robot
    :type manufacturer: str, optional
    :param base: Location of the base is the world frame
    :type base: SE3, optional
    :param tool: Offset of the flange of the robot to the end-effector
    :type tool: SE3, optional
    :param gravity: The gravity vector
    :type n: ndarray(3)
    An ERobot represents the kinematics of a serial-link manipulator with
    one or more branches.
    From ETS
    --------
    Example:
    .. runblock:: pycon
        >>> from roboticstoolbox import ETS, ERobot
        >>> ets = ETS.rz() * ETS.ry() * ETS.tz(1) * ETS.ry() * ETS.tz(1)
        >>> robot = ERobot(ets)
        >>> print(robot)
    The ETS is partitioned such that a new link frame is created **after** every
    joint variable.
    From list of Links
    -------------------
    Example:
    .. runblock:: pycon
        >>> from roboticstoolbox import ETS, ERobot
        >>> link1 = Link(ETS.rz(), name='link1')
        >>> link2 = Link(ETS.ry(), name='link2', parent=link1)
        >>> link3 = Link(ETS.tz(1) * ETS.ry(), name='link3', parent=link2)
        >>> link4 = Link(ETS.tz(1), name='ee', parent=link3)
        >>> robot = ERobot([link1, link2, link3, link4])
        >>> print(robot)
    A number of ``Link`` objects are created, each has a transform with
    respect to the previous frame, and all except the first link have a parent.
    The implicit parent of the first link is the base.
    The parent also can be specified as a string, and its name is mapped to the
    parent link by name in ``ERobot``.
    If no ``parent`` arguments are given it is assumed the links are in
    sequential order, and the parent hierarchy will be automatically
    established.
    .. runblock:: pycon
        >>> from roboticstoolbox import ETS, ERobot
        >>> robot = ERobot([
        >>>     Link(ETS.rz(), name='link1'),
        >>>     Link(ETS.ry(), name='link2'),
        >>>     Link(ETS.tz(1) * ETS.ry(), name='link3'),
        >>>     Link(ETS.tz(1), name='ee')
        >>>             ])
        >>> print(robot)
    Branched robots
    ---------------
    Example:
    .. runblock:: pycon
        >>> robot = ERobot([
        >>>    Link(ETS.rz(), name='link1'),
        >>>    Link(ETS.tx(1) * ETS.ty(-0.5) * ETS.rz(), name='link2', parent='link1'),
        >>>    Link(ETS.tx(1), name='ee_1', parent='link2'),
        >>>    Link(ETS.tx(1) * ETS.ty(0.5) * ETS.rz(), name='link3', parent='link1'),
        >>>    Link(ETS.tx(1), name='ee_2', parent='link3')
        >>>             ])
        >>> print(robot)
    :references:
        - Kinematic Derivatives using the Elementary Transform Sequence,
          J. Haviland and P. Corke
    """  # noqa E501

    def __init__(self, links, gripper_links=None, checkjindex=True, **kwargs):
        self._path_cache_fknm = {}
        self._path_cache = {}
        self._eye_fknm = eye(4)

        self._linkdict = {}
        self._n = 0
        self._ee_links = []

        # Ordered links, we reorder the input elinks to be in depth first
        # search order
        orlinks = []

        # # check all the incoming Link objects
        # n = 0
        # for k, link in enumerate(links):
        #     # if link has no name, give it one
        #     if link.name is None or link.name == "":
        #         link.name = f"link-{k}"
        #     link.number = k + 1

        #     # put it in the link dictionary, check for duplicates
        #     if link.name in self._linkdict:
        #         raise ValueError(f"link name {link.name} is not unique")
        #     self._linkdict[link.name] = link

        #     if link.isjoint:
        #         n += 1

        # # resolve parents given by name, within the context of
        # # this set of links
        # for link in links:
        #     if link.parent is None and link.parent_name is not None:
        #         link._parent = self._linkdict[link.parent_name]

        # if all([link.parent is None for link in links]):
        #     # no parent links were given, assume they are sequential
        #     for i in range(len(links) - 1):
        #         links[i + 1]._parent = links[i]

        # self._n = n

        # # scan for base
        # for link in links:
        #     # is this a base link?
        #     if link._parent is None:
        #         try:
        #             if self._base_link is not None:
        #                 raise ValueError("Multiple base links")
        #         except AttributeError:
        #             pass

        #         self._base_link = link
        #     else:
        #         # no, update children of this link's parent
        #         link._parent._children.append(link)

        # if self.base_link is None:  # Pragma: nocover
        #     raise ValueError(
        #         "Invalid link configuration provided, must have a base link"
        #     )

        # # Scene node, set links between the links
        # for link in links:
        #     if link.parent is not None:
        #         link.scene_parent = link.parent

        # # Set up the gripper, make a list containing the root of all
        # # grippers
        # if gripper_links is not None:
        #     if isinstance(gripper_links, Link):
        #         gripper_links = [gripper_links]
        # else:
        #     gripper_links = []

        # # An empty list to hold all grippers
        # self._grippers = []

        # # Make a gripper object for each gripper
        # for link in gripper_links:
        #     g_links = self.dfs_links(link)

        #     # Remove gripper links from the robot
        #     for g_link in g_links:
        #         # print(g_link)
        #         links.remove(g_link)

        #     # Save the gripper object
        #     self._grippers.append(Gripper(g_links, name=link.name))

        # # Subtract the n of the grippers from the n of the robot
        # for gripper in self._grippers:
        #     self._n -= gripper.n

        # # Set the ee links
        # self.ee_links = []
        # if len(gripper_links) == 0:
        #     for link in links:
        #         # is this a leaf node? and do we not have any grippers
        #         if len(link.children) == 0:
        #             # no children, must be an end-effector
        #             self.ee_links.append(link)
        # else:
        #     for link in gripper_links:
        #         # use the passed in value
        #         self.ee_links.append(link.parent)  # type: ignore

        # # assign the joint indices
        # if all([link.jindex is None or link.ets._auto_jindex for link in links]):
        #     # no joints have an index
        #     jindex = [0]  # "mutable integer" hack

        #     def visit_link(link, jindex):
        #         # if it's a joint, assign it a jindex and increment it
        #         if link.isjoint and link in links:
        #             link.jindex = jindex[0]
        #             jindex[0] += 1

        #         if link in links:
        #             orlinks.append(link)

        #     # visit all links in DFS order
        #     self.dfs_links(self.base_link, lambda link: visit_link(link, jindex))

        # elif all([link.jindex is not None for link in links if link.isjoint]):
        #     # jindex set on all, check they are unique and contiguous
        #     if checkjindex:
        #         jset = set(range(self._n))
        #         for link in links:
        #             if link.isjoint and link.jindex not in jset:
        #                 raise ValueError(
        #                     f"joint index {link.jindex} was " "repeated or out of range"
        #                 )
        #             jset -= set([link.jindex])
        #         if len(jset) > 0:  # pragma nocover  # is impossible
        #             raise ValueError(f"joints {jset} were not assigned")
        #     orlinks = links
        # else:
        #     # must be a mixture of Links with/without jindex
        #     raise ValueError("all links must have a jindex, or none have a jindex")

        # self._nbranches = sum([link.nchildren == 0 for link in links])

        # # Set up qlim
        # qlim = zeros((2, self.n))
        # j = 0

        # for i in range(len(orlinks)):
        #     if orlinks[i].isjoint:
        #         qlim[:, j] = orlinks[i].qlim
        #         j += 1
        # self._qlim = qlim

        # self._valid_qlim = False
        # for i in range(self.n):
        #     if any(qlim[:, i] != 0) and not any(isnan(qlim[:, i])):
        #         self._valid_qlim = True

        # Initialise Robot object
        super().__init__(orlinks, **kwargs)

    # --------------------------------------------------------------------- #

    def dfs_links(self, start, func=None):
        """
        Visit all links from start in depth-first order and will apply
        func to each visited link
        :param start: the link to start at
        :type start: Link
        :param func: An optional function to apply to each link as it is found
        :type func: function
        :returns: A list of links
        :rtype: list of Link
        """
        visited = []

        def vis_children(link):
            visited.append(link)
            if func is not None:
                func(link)

            for li in link.children:
                if li not in visited:
                    vis_children(li)

        vis_children(start)

        return visited

    def _get_limit_links(
        self,
        end: Union[Gripper, Link, str, None] = None,
        start: Union[Gripper, Link, str, None] = None,
    ) -> Tuple[Link, Union[Link, Gripper], Union[None, SE3]]:
        """
        Get and validate an end-effector, and a base link
        :param end: end-effector or gripper to compute forward kinematics to
        :type end: str or Link or Gripper, optional
        :param start: name or reference to a base link, defaults to None
        :type start: str or Link, optional
        :raises ValueError: link not known or ambiguous
        :raises ValueError: [description]
        :raises TypeError: unknown type provided
        :return: end-effector link, base link, and tool transform of gripper
            if applicable
        :rtype: Link, Elink, SE3 or None
        Helper method to find or validate an end-effector and base link.
        """

        # Try cache
        # if self._cache_end is not None:
        #     return self._cache_end, self._cache_start, self._cache_end_tool

        tool = None
        if end is None:

            if len(self.grippers) > 1:
                end_ret = self.grippers[0].links[0]
                tool = self.grippers[0].tool
                if len(self.grippers) > 1:
                    # Warn user: more than one gripper
                    print("More than one gripper present, using robot.grippers[0]")
            elif len(self.grippers) == 1:
                end_ret = self.grippers[0].links[0]
                tool = self.grippers[0].tool

            # no grippers, use ee link if just one
            elif len(self.ee_links) > 1:
                end_ret = self.ee_links[0]
                if len(self.ee_links) > 1:
                    # Warn user: more than one EE
                    print("More than one end-effector present, using robot.ee_links[0]")
            else:
                end_ret = self.ee_links[0]

            # Cache result
            self._cache_end = end
            self._cache_end_tool = tool
        else:

            # Check if end corresponds to gripper
            for gripper in self.grippers:
                if end == gripper or end == gripper.name:
                    tool = gripper.tool
                    # end_ret = gripper.links[0]

            # otherwise check for end in the links
            end_ret = self._getlink(end)

        if start is None:
            start_ret = self.base_link

            # Cache result
            self._cache_start = start
        else:
            # start effector is specified
            start_ret = self._getlink(start)

        return end_ret, start_ret, tool

# =========================================================================== #


class ERobot(BaseERobot):
    def __init__(self, arg, urdf_string=None, urdf_filepath=None, **kwargs):

        if isinstance(arg, ERobot):
            # We're passed an ERobot, clone it
            # We need to preserve the parent link as we copy

            # Copy each link within the robot
            links = [deepcopy(link) for link in arg.links]
            gripper_links = []

            for gripper in arg.grippers:
                glinks = []
                for link in gripper.links:
                    glinks.append(deepcopy(link))

                gripper_links.append(glinks[0])
                links = links + glinks

            # print(links[9] is gripper_links[0])
            # print(gripper_links)

            # Sever parent connection, but save the string
            # The constructor will piece this together for us
            for link in links:
                link._children = []
                if link.parent is not None:
                    link._parent_name = link.parent.name
                    link._parent = None

            # gripper_parents = []

            # # Make a list of old gripper links
            # for gripper in arg.grippers:
            #     gripper_parents.append(gripper.links[0].name)

            # gripper_links = []

            # def dfs(node, node_copy):
            #     for child in node.children:
            #         child_copy = child.copy(node_copy)
            #         links.append(child_copy)

            #         # If this link was a gripper link, add to the list
            #         if child_copy.name in gripper_parents:
            #             gripper_links.append(child_copy)

            #         dfs(child, child_copy)

            # link0 = arg.links[0]
            # links.append(arg.links[0].copy())
            # dfs(link0, links[0])

            # print(gripper_links[0].jindex)

            super().__init__(links, gripper_links=gripper_links, **kwargs)

            for i, gripper in enumerate(self.grippers):
                gripper.tool = arg.grippers[i].tool.copy()

            # if arg.qdlim is not None:
            #     self.qdlim = arg.qdlim

            self._urdf_string = arg.urdf_string
            self._urdf_filepath = arg.urdf_filepath

        else:
            self._urdf_string = urdf_string
            self._urdf_filepath = urdf_filepath

            if isinstance(arg, DHRobot):
                # we're passed a DHRobot object
                # TODO handle dynamic parameters if given
                arg = arg.ets

            if isinstance(arg, ETS):
                # we're passed an ETS string
                links = []
                # chop it up into segments, a link frame after every joint
                parent = None
                for j, ets_j in enumerate(arg.split()):
                    elink = Link(ETS(ets_j), parent=parent, name=f"link{j:d}")
                    if (
                        elink.qlim is None
                        and elink.v is not None
                        and elink.v.qlim is not None
                    ):
                        elink.qlim = elink.v.qlim
                    parent = elink
                    links.append(elink)

            elif islistof(arg, Link):
                links = arg

            else:
                raise TypeError("constructor argument must be ETS or list of Link")

            super().__init__(links, **kwargs)



    def get_path(self, end=None, start=None):
        """
        Find a path from start to end. The end must come after
        the start (ie end must be further away from the base link
        of the robot than start) in the kinematic chain and both links
        must be a part of the same branch within the robot structure. This
        method is a work in progress while an approach which generalises
        to all applications is designed.
        :param end: end-effector or gripper to compute forward kinematics to
        :type end: str or Link or Gripper, optional
        :param start: name or reference to a base link, defaults to None
        :type start: str or Link, optional
        :raises ValueError: link not known or ambiguous
        :return: the path from start to end
        :rtype: list of Link
        """
        path = []
        n = 0

        end, start, tool = self._get_limit_links(end=end, start=start)

        # This is way faster than doing if x in y method
        try:
            return self._path_cache[start.name][end.name]
        except KeyError:
            pass

        if start.name not in self._path_cache:
            self._path_cache[start.name] = {}
            # self._path_cache_fknm[start.name] = {}

        link = end

        path.append(link)
        if link.isjoint:
            n += 1

        while link != start:
            link = link.parent
            if link is None:
                raise ValueError(
                    f"cannot find path from {start.name} to" f" {end.name}"
                )
            path.append(link)
            if link.isjoint:
                n += 1

        path.reverse()
        # path_fknm = [x._fknm for x in path]

        if tool is None:
            tool = SE3()

        self._path_cache[start.name][end.name] = (path, n, tool)
        # self._path_cache_fknm[start.name][end.name] = (path_fknm, n, tool.A)

        return path, n, tool

    def link_collision_damper(
        self,
        shape,
        q=None,
        di=0.3,
        ds=0.05,
        xi=1.0,
        end=None,
        start=None,
        collision_list=None,
    ):
        """
        Formulates an inequality contraint which, when optimised for will
        make it impossible for the robot to run into a collision. Requires
        See examples/neo.py for use case
        :param ds: The minimum distance in which a joint is allowed to
            approach the collision object shape
        :type ds: float
        :param di: The influence distance in which the velocity
            damper becomes active
        :type di: float
        :param xi: The gain for the velocity damper
        :type xi: float
        :param from_link: The first link to consider, defaults to the base
            link
        :type from_link: Link
        :param to_link: The last link to consider, will consider all links
            between from_link and to_link in the robot, defaults to the
            end-effector link
        :type to_link: Link
        :returns: Ain, Bin as the inequality contraints for an omptimisor
        :rtype: ndarray(6), ndarray(6)
        """

        end, start, _ = self._get_limit_links(start=start, end=end)

        links, n, _ = self.get_path(start=start, end=end)

        # if q is None:
        #     q = copy(self.q)
        # else:
        #     q = getvector(q, n)

        j = 0
        Ain = None
        bin = None

        def indiv_calculation(link, link_col, q):
            d, wTlp, wTcp = link_col.closest_point(shape, di)

            if d is not None:
                lpTcp = -wTlp + wTcp

                norm = lpTcp / d
                norm_h = expand_dims(concatenate((norm, [0, 0, 0])), axis=0)

                # tool = (self.fkine(q, end=link).inv() * SE3(wTlp)).A[:3, 3]

                # Je = self.jacob0(q, end=link, tool=tool)
                # Je[:3, :] = self._T[:3, :3] @ Je[:3, :]

                # n_dim = Je.shape[1]
                # dp = norm_h @ shape.v
                # l_Ain = zeros((1, self.n))

                Je = self.jacobe(q, start=start, end=link, tool=link_col.T)
                n_dim = Je.shape[1]
                dp = norm_h @ shape.v
                l_Ain = zeros((1, n))

                l_Ain[0, :n_dim] = 1 * norm_h @ Je
                l_bin = (xi * (d - ds) / (di - ds)) + dp
            else:
                l_Ain = None
                l_bin = None

            return l_Ain, l_bin

        for link in links:
            if link.isjoint:
                j += 1

            if collision_list is None:
                col_list = link.collision
            else:
                col_list = collision_list[j - 1]

            for link_col in col_list:
                l_Ain, l_bin = indiv_calculation(link, link_col, q)

                if l_Ain is not None and l_bin is not None:
                    if Ain is None:
                        Ain = l_Ain
                    else:
                        Ain = concatenate((Ain, l_Ain))

                    if bin is None:
                        bin = array(l_bin)
                    else:
                        bin = concatenate((bin, l_bin))

        return Ain, bin

    def vision_collision_damper(
        self,
        shape,
        camera=None,
        camera_n=0,
        q=None,
        di=0.3,
        ds=0.05,
        xi=1.0,
        end=None,
        start=None,
        collision_list=None,
    ):
        """
        Formulates an inequality contraint which, when optimised for will
        make it impossible for the robot to run into a line of sight.
        See examples/fetch_vision.py for use case
        :param camera: The camera link, either as a robotic link or SE3
            pose
        :type camera: ERobot or SE3
        :param camera_n: Degrees of freedom of the camera link
        :type camera_n: int
        :param ds: The minimum distance in which a joint is allowed to
            approach the collision object shape
        :type ds: float
        :param di: The influence distance in which the velocity
            damper becomes active
        :type di: float
        :param xi: The gain for the velocity damper
        :type xi: float
        :param from_link: The first link to consider, defaults to the base
            link
        :type from_link: ELink
        :param to_link: The last link to consider, will consider all links
            between from_link and to_link in the robot, defaults to the
            end-effector link
        :type to_link: ELink
        :returns: Ain, Bin as the inequality contraints for an omptimisor
        :rtype: ndarray(6), ndarray(6)
        """

        if start is None:
            start = self.base_link

        if end is None:
            end = self.ee_link

        links, n, _ = self.get_path(start=start, end=end)

        j = 0
        Ain = None
        bin = None

        def rotation_between_vectors(a, b):
            a = a / npnorm(a)
            b = b / npnorm(b)

            angle = arccos(dot(a, b))
            axis = cross(a, b)

            return SE3.AngleAxis(angle, axis)

        if isinstance(camera, ERobot):
            wTcp = camera.fkine(camera.q).A[:3, 3]
        elif isinstance(camera, SE3):
            wTcp = camera.t

        wTtp = shape.T[:3, -1]

        # Create line of sight object
        los_mid = SE3((wTcp + wTtp) / 2)
        los_orientation = rotation_between_vectors(array([0.0, 0.0, 1.0]), wTcp - wTtp)

        los = Cylinder(
            radius=0.001,
            length=npnorm(wTcp - wTtp),
            base=(los_mid * los_orientation),
        )

        def indiv_calculation(link, link_col, q):
            d, wTlp, wTvp = link_col.closest_point(los, di)

            if d is not None:
                lpTvp = -wTlp + wTvp

                norm = lpTvp / d
                norm_h = expand_dims(concatenate((norm, [0, 0, 0])), axis=0)

                tool = SE3((inv(self.fkine(q, end=link).A) @ SE3(wTlp).A)[:3, 3])

                Je = self.jacob0(q, end=link, tool=tool.A)
                Je[:3, :] = self._T[:3, :3] @ Je[:3, :]
                n_dim = Je.shape[1]

                if isinstance(camera, ERobot):
                    Jv = camera.jacob0(camera.q)
                    Jv[:3, :] = self._T[:3, :3] @ Jv[:3, :]

                    Jv *= npnorm(wTvp - shape.T[:3, -1]) / los.length

                    dpc = norm_h @ Jv
                    dpc = concatenate(
                        (
                            dpc[0, :-camera_n],
                            zeros(self.n - (camera.n - camera_n)),
                            dpc[0, -camera_n:],
                        )
                    )
                else:
                    dpc = zeros((1, self.n + camera_n))

                dpt = norm_h @ shape.v
                dpt *= npnorm(wTvp - wTcp) / los.length

                l_Ain = zeros((1, self.n + camera_n))
                l_Ain[0, :n_dim] = norm_h @ Je
                l_Ain -= dpc
                l_bin = (xi * (d - ds) / (di - ds)) + dpt
            else:
                l_Ain = None
                l_bin = None

            return l_Ain, l_bin

        for link in links:
            if link.isjoint:
                j += 1

            if collision_list is None:
                col_list = link.collision
            else:
                col_list = collision_list[j - 1]

            for link_col in col_list:
                l_Ain, l_bin = indiv_calculation(link, link_col, q)

                if l_Ain is not None and l_bin is not None:
                    if Ain is None:
                        Ain = l_Ain
                    else:
                        Ain = concatenate((Ain, l_Ain))

                    if bin is None:
                        bin = array(l_bin)
                    else:
                        bin = concatenate((bin, l_bin))

        return Ain, bin

    # inverse dynamics (recursive Newton-Euler) using spatial vector notation
    def rne(self, q, qd, qdd, symbolic=False, gravity=None):

        n = self.n

        # allocate intermediate variables
        Xup = SE3.Alloc(n)
        Xtree = SE3.Alloc(n)

        v = SpatialVelocity.Alloc(n)
        a = SpatialAcceleration.Alloc(n)
        f = SpatialForce.Alloc(n)
        I = SpatialInertia.Alloc(n)  # noqa
        s = []  # joint motion subspace

        if symbolic:
            Q = empty((n,), dtype="O")  # joint torque/force
        else:
            Q = empty((n,))  # joint torque/force

        # TODO Should the dynamic parameters of static links preceding joint be
        # somehow merged with the joint?

        # A temp variable to handle static joints
        Ts = SE3()

        # A counter through joints
        j = 0

        # initialize intermediate variables
        for link in self.links:
            if link.isjoint:
                I[j] = SpatialInertia(m=link.m, r=link.r)
                if symbolic and link.Ts is None:
                    Xtree[j] = SE3(eye(4, dtype="O"), check=False)
                else:
                    Xtree[j] = Ts * SE3(link.Ts, check=False)

                if link.v is not None:
                    s.append(link.v.s)

                # Increment the joint counter
                j += 1

                # Reset the Ts tracker
                Ts = SE3()
            else:
                # TODO Keep track of inertia and transform???
                Ts *= SE3(link.Ts, check=False)

        if gravity is None:
            a_grav = -SpatialAcceleration(self.gravity)
        else:
            a_grav = -SpatialAcceleration(gravity)

        # forward recursion
        for j in range(0, n):
            vJ = SpatialVelocity(s[j] * qd[j])

            # transform from parent(j) to j
            Xup[j] = SE3(self.links[j].A(q[j])).inv()

            if self.links[j].parent is None:
                v[j] = vJ
                a[j] = Xup[j] * a_grav + SpatialAcceleration(s[j] * qdd[j])
            else:
                jp = self.links[j].parent.jindex  # type: ignore
                v[j] = Xup[j] * v[jp] + vJ
                a[j] = Xup[j] * a[jp] + SpatialAcceleration(s[j] * qdd[j]) + v[j] @ vJ

            f[j] = I[j] * a[j] + v[j] @ (I[j] * v[j])

        # backward recursion
        for j in reversed(range(0, n)):

            # next line could be dot(), but fails for symbolic arguments
            Q[j] = sum(f[j].A * s[j])

            if self.links[j].parent is not None:
                jp = self.links[j].parent.jindex  # type: ignore
                f[jp] = f[jp] + Xup[j] * f[j]

        return Q

    # --------------------------------------------------------------------- #

# =========================================================================== #


class ERobot2(BaseERobot):
    def __init__(self, arg, **kwargs):

        if isinstance(arg, ETS2):
            # we're passed an ETS string
            links = []
            # chop it up into segments, a link frame after every joint
            parent = None
            for j, ets_j in enumerate(arg.split()):
                elink = Link2(ETS2(ets_j), parent=parent, name=f"link{j:d}")
                parent = elink
                if (
                    elink.qlim is None
                    and elink.v is not None
                    and elink.v.qlim is not None
                ):
                    elink.qlim = elink.v.qlim
                links.append(elink)

        elif islistof(arg, Link2):
            links = arg
        else:
            raise TypeError("constructor argument must be ETS2 or list of Link2")

        super().__init__(links, **kwargs)

        # should just set it to None
        self.base = SE2()  # override superclass

    @property
    def base(self) -> SE2:
        """
        Get/set robot base transform (Robot superclass)

        - ``robot.base`` is the robot base transform

        :return: robot tool transform
        :rtype: SE2 instance

        - ``robot.base = ...`` checks and sets the robot base transform

        .. note:: The private attribute ``_base`` will be None in the case of
            no base transform, but this property will return ``SE3()`` which
            is an identity matrix.
        """
        if self._base is None:
            self._base = SE2()

        # return a copy, otherwise somebody with
        # reference to the base can change it
        return self._base.copy()

    @base.setter
    def base(self, T):
        if T is None:
            self._base = T
        elif isinstance(self, ERobot2):
            # 2D robot
            if isinstance(T, SE2):
                self._base = T
            elif SE2.isvalid(T):
                self._tool = SE2(T, check=True)
        else:
            raise ValueError("base must be set to None (no tool) or SE2")

    def jacob0(self, q, start=None, end=None):
        return self.ets(start, end).jacob0(q)

    def jacobe(self, q, start=None, end=None):
        return self.ets(start, end).jacobe(q)

    def fkine(self, q, end=None, start=None):

        return self.ets(start, end).fkine(q)


# --------------------------------------------------------------------- #

# def teach(
#         self,
#         q=None,
#         block=True,
#         limits=None,
#         vellipse=False,
#         fellipse=False,
#         eeframe=True,
#         name=False,
#         unit='rad',
#         backend='pyplot2'):
#     """
#     2D Graphical teach pendant
#     :param block: Block operation of the code and keep the figure open
#     :type block: bool
#     :param q: The joint configuration of the robot (Optional,
#         if not supplied will use the stored q values).
#     :type q: float ndarray(n)
#     :param limits: Custom view limits for the plot. If not supplied will
#         autoscale, [x1, x2, y1, y2]
#     :type limits: array_like(4)
#     :param vellipse: (Plot Option) Plot the velocity ellipse at the
#         end-effector
#     :type vellipse: bool
#     :param vellipse: (Plot Option) Plot the force ellipse at the
#         end-effector
#     :type vellipse: bool
#     :param eeframe: (Plot Option) Plot the end-effector coordinate frame
#         at the location of the end-effector. Uses three arrows, red,
#         green and blue to indicate the x, y, and z-axes.
#     :type eeframe: bool
#     :param name: (Plot Option) Plot the name of the robot near its base
#     :type name: bool
#     :param unit: angular units: 'rad' [default], or 'deg'
#     :type unit: str

#     :return: A reference to the PyPlot object which controls the
#         matplotlib figure
#     :rtype: PyPlot
#     - ``robot.teach2(q)`` creates a 2D matplotlib plot which allows the
#       user to "drive" a graphical robot using a graphical slider panel.
#       The robot's inital joint configuration is ``q``. The plot will
#       autoscale with an aspect ratio of 1.
#     - ``robot.teach2()`` as above except the robot's stored value of ``q``
#       is used.
#     .. note::
#         - Program execution is blocked until the teach window is
#           dismissed.  If ``block=False`` the method is non-blocking but
#           you need to poll the window manager to ensure that the window
#           remains responsive.
#         - The slider limits are derived from the joint limit properties.
#           If not set then:
#             - For revolute joints they are assumed to be [-pi, +pi]
#             - For prismatic joint they are assumed unknown and an error
#               occurs.
#           If not set then
#             - For revolute joints they are assumed to be [-pi, +pi]
#             - For prismatic joint they are assumed unknown and an error
#               occurs.
#     """

#     if q is None:
#         q = zeros((self.n,))
#     else:
#         q = getvector(q, self.n)

#     if unit == 'deg':
#         q = self.toradians(q)

#     # Make an empty 3D figure
#     env = self._get_graphical_backend(backend)

#     # Add the robot to the figure in readonly mode
#     env.launch('Teach ' + self.name, limits=limits)
#     env.add(
#         self, readonly=True,
#         eeframe=eeframe, name=name)

#     env._add_teach_panel(self, q)

#     if limits is None:
#         limits = r_[-1, 1, -1, 1] * self.reach * 1.5
#         env.ax.set_xlim([limits[0], limits[1]])
#         env.ax.set_ylim([limits[2], limits[3]])

#     if vellipse:
#         vell = self.vellipse(centre='ee', scale=0.5)
#         env.add(vell)

#     if fellipse:
#         fell = self.fellipse(centre='ee')
#         env.add(fell)

#     # Keep the plot open
#     if block:           # pragma: no cover
#         env.hold()

#     return env


if __name__ == "__main__":  # pragma nocover

    e1 = Link(ETS(ET.Rz()), jindex=0)
    e2 = Link(ETS(ET.Rz()), jindex=1, parent=e1)
    e3 = Link(ETS(ET.Rz()), jindex=2, parent=e2)
    e4 = Link(ETS(ET.Rz()), jindex=5, parent=e3)

    ERobot([e1, e2, e3, e4])
